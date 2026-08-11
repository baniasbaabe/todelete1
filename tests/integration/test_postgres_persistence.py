"""PostgresPersistence against a real PostgreSQL Testcontainer."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from habit_tracker.application.checkin_session import CheckinResult, CheckinSession
from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.value_objects.frequency import Frequency
from habit_tracker.domain.value_objects.habit_name import HabitName
from habit_tracker.domain.value_objects.verification_policy import VerificationPolicy
from habit_tracker.infrastructure.persistence.postgres_persistence import PostgresPersistence


@pytest_asyncio.fixture
async def persistence(
    postgres_async_url: str,
    test_engine: AsyncEngine,
) -> AsyncGenerator[PostgresPersistence]:
    async with test_engine.begin() as connection:
        await connection.execute(text("DELETE FROM bot_persistence"))

    store = PostgresPersistence(database_url=postgres_async_url)
    try:
        yield store
    finally:
        await store.close()
        async with test_engine.begin() as connection:
            await connection.execute(text("DELETE FROM bot_persistence"))


class TestBotData:
    async def test_missing_bot_data_is_empty(self, persistence: PostgresPersistence) -> None:
        assert await persistence.get_bot_data() == {}

    async def test_update_overwrite_and_refresh(self, persistence: PostgresPersistence) -> None:
        await persistence.update_bot_data({"old": True})
        await persistence.update_bot_data({"count": 42})

        assert await persistence.get_bot_data() == {"count": 42}
        live = {"stale": True}
        assert await persistence.refresh_bot_data(live) is None
        assert live == {"count": 42}


class TestUserAndChatData:
    async def test_user_rows_roundtrip_with_integer_ids(self, persistence: PostgresPersistence) -> None:
        await persistence.update_user_data(123, {"name": "Alice"})
        await persistence.update_user_data(-100, {"group": True})

        assert await persistence.get_user_data() == {
            123: {"name": "Alice"},
            -100: {"group": True},
        }

    async def test_chat_and_user_prefixes_do_not_bleed(self, persistence: PostgresPersistence) -> None:
        await persistence.update_user_data(1, {"kind": "user"})
        await persistence.update_chat_data(1, {"kind": "chat"})

        assert await persistence.get_user_data() == {1: {"kind": "user"}}
        assert await persistence.get_chat_data() == {1: {"kind": "chat"}}

    async def test_drop_only_removes_the_requested_row(self, persistence: PostgresPersistence) -> None:
        await persistence.update_user_data(1, {"a": 1})
        await persistence.update_user_data(2, {"b": 2})
        await persistence.drop_user_data(1)

        assert await persistence.get_user_data() == {2: {"b": 2}}

    async def test_refresh_mutates_and_clears_in_place(self, persistence: PostgresPersistence) -> None:
        await persistence.update_chat_data(5, {"message": "hello"})
        live = {"old": True}
        await persistence.refresh_chat_data(5, live)
        assert live == {"message": "hello"}

        missing = {"old": True}
        await persistence.refresh_chat_data(999, missing)
        assert missing == {}

    async def test_python_values_are_serialized_as_json(self, persistence: PostgresPersistence) -> None:
        created_at = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
        await persistence.update_user_data(7, {"created_at": created_at})

        assert await persistence.get_user_data() == {7: {"created_at": str(created_at)}}


class TestPoolLifecycle:
    async def test_concurrent_first_callers_share_the_real_pool(
        self,
        postgres_async_url: str,
    ) -> None:
        persistence = PostgresPersistence(database_url=postgres_async_url)
        try:
            first, second = await asyncio.gather(persistence._get_pool(), persistence._get_pool())
            assert first is second
        finally:
            await persistence.close()

    async def test_close_closes_the_real_pool(self, postgres_async_url: str) -> None:
        persistence = PostgresPersistence(database_url=postgres_async_url)
        pool = await persistence._get_pool()

        await persistence.close()

        assert pool._closed is True


class TestCheckinSessionRoundtrip:
    async def test_roundtrip_via_user_data(self, persistence: PostgresPersistence) -> None:
        habit = Habit(
            id=1,
            user_id=42,
            name=HabitName("Morning Run"),
            description="Run 5km each morning",
            frequency=Frequency.DAILY,
            verification_policy=VerificationPolicy.NONE,
            is_active=True,
            created_at=datetime(2026, 1, 1, 8, 0, tzinfo=UTC),
        )
        session = CheckinSession.start(user_id=42, habits=[habit])
        session.results.append(CheckinResult(habit_name="Morning Run", completed=True, skipped=False))

        await persistence.update_user_data(42, {"checkin_session": session.to_dict()})
        restored = CheckinSession.from_dict((await persistence.get_user_data())[42]["checkin_session"])

        assert restored.user_id == session.user_id
        assert restored.habits == session.habits
        assert restored.results == session.results
