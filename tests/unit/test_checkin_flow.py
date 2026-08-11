"""End-to-end check-in flow through the real handlers.

The presentation layer previously had no tests at all, which is why a total
outage (dependencies wiped at startup) and an inert memory feature both went
unnoticed. These drive the real handler functions, substituting only the
transaction boundary and the external services.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.ext import ApplicationBuilder

from habit_tracker.application.checkin_session import TTL_HOURS
from habit_tracker.application.use_cases.create_habit import CreateHabit
from habit_tracker.application.use_cases.record_checkin_insight import INSIGHT_CATEGORY
from habit_tracker.application.use_cases.register_user import RegisterUser
from habit_tracker.domain.value_objects import HabitName, TelegramId
from habit_tracker.domain.value_objects.verification_policy import VerificationPolicy
from habit_tracker.infrastructure.database.unit_of_work import UnitOfWork
from habit_tracker.infrastructure.persistence.postgres_persistence import PostgresPersistence
from habit_tracker.presentation.dependencies import Dependencies, install
from habit_tracker.presentation.handlers.checkin_handlers import checkin_handler
from habit_tracker.presentation.handlers.proof_handlers import text_response_handler
from tests.unit.conftest import (
    FakeMemoryStore,
    FakePatternAnalyzer,
    FakeProofVerifier,
    InMemoryCompletionRepository,
    InMemoryHabitRepository,
    InMemoryUserRepository,
)

TELEGRAM_ID = 987654


class _InMemoryDependencies(Dependencies):
    """Dependencies whose unit of work is backed by the in-memory repositories."""

    def __init__(self, users, habits, completions, **kwargs) -> None:
        super().__init__(db=SimpleNamespace(), **kwargs)
        object.__setattr__(self, "_repos", (users, habits, completions))

    @asynccontextmanager
    async def unit_of_work(self):
        users, habits, completions = self._repos
        yield UnitOfWork(
            users=users,
            habits=habits,
            completions=completions,
            session=SimpleNamespace(commit=AsyncMock()),
        )


@pytest.fixture
def env():
    users = InMemoryUserRepository()
    habits = InMemoryHabitRepository()
    completions = InMemoryCompletionRepository()
    memory = FakeMemoryStore()

    deps = _InMemoryDependencies(
        users,
        habits,
        completions,
        proof_verifier=FakeProofVerifier(result_verified=True),
        memory_store=memory,
        pattern_analyzer=FakePatternAnalyzer(),
    )

    app = ApplicationBuilder().token("123:ABC").build()
    install(app, deps)

    context = SimpleNamespace(application=app, user_data={}, bot=None)
    return SimpleNamespace(users=users, habits=habits, completions=completions, memory=memory, app=app, context=context)


def _update(text: str | None = None) -> SimpleNamespace:
    message = SimpleNamespace(text=text, reply_text=AsyncMock(), photo=[])
    return SimpleNamespace(message=message, effective_user=SimpleNamespace(id=TELEGRAM_ID, username="tester"))


async def _seed(env, *, policy=VerificationPolicy.NONE):
    user, _ = await RegisterUser(env.users).execute(TelegramId(TELEGRAM_ID))
    await CreateHabit(env.users, env.habits).execute(
        TelegramId(TELEGRAM_ID), HabitName("gym"), verification_policy=policy
    )
    return user


async def _drain_background_tasks(app) -> None:
    """Await the fire-and-forget insight write."""
    for _ in range(5):
        await asyncio.sleep(0)
    if app._Application__create_task_tasks:
        await asyncio.gather(*app._Application__create_task_tasks, return_exceptions=True)


class TestCheckinFlow:
    async def test_checkin_opens_a_session(self, env) -> None:
        await _seed(env)
        update = _update()

        await checkin_handler(update, env.context)

        assert "checkin_session" in env.context.user_data
        update.message.reply_text.assert_awaited_once()
        assert "gym" in update.message.reply_text.await_args.args[0]

    async def test_session_stores_persistent_user_id_not_telegram_id(self, env) -> None:
        user = await _seed(env)

        await checkin_handler(_update(), env.context)

        assert env.context.user_data["checkin_session"]["user_id"] == user.id
        assert env.context.user_data["checkin_session"]["user_id"] != TELEGRAM_ID

    async def test_completing_a_checkin_records_a_memory_insight(self, env) -> None:
        """The write half of the memory feature, exercised through the handlers."""
        user = await _seed(env)
        await checkin_handler(_update(), env.context)

        reply = _update("yes")
        await text_response_handler(reply, env.context)
        await _drain_background_tasks(env.app)

        assert len(env.memory.stored) == 1
        assert env.memory.stored[0]["user_id"] == user.id
        assert env.memory.stored[0]["category"] == INSIGHT_CATEGORY
        assert "completed gym" in env.memory.stored[0]["insight"]

    async def test_insight_is_readable_back_under_the_same_user_id(self, env) -> None:
        user = await _seed(env)
        await checkin_handler(_update(), env.context)

        await text_response_handler(_update("yes"), env.context)
        await _drain_background_tasks(env.app)

        assert len(await env.memory.get_insights(user.id)) == 1
        assert await env.memory.get_insights(TELEGRAM_ID) == []

    async def test_completing_a_checkin_clears_the_session(self, env) -> None:
        await _seed(env)
        await checkin_handler(_update(), env.context)

        await text_response_handler(_update("yes"), env.context)

        assert "checkin_session" not in env.context.user_data

    @pytest.mark.parametrize("second_reply", ["yes", "skip"])
    async def test_second_habit_finishes_after_persistence_refresh(self, env, monkeypatch, second_reply: str) -> None:
        await _seed(env)
        await CreateHabit(env.users, env.habits).execute(TelegramId(TELEGRAM_ID), HabitName("read"))
        await checkin_handler(_update(), env.context)
        stale_user_data = deepcopy(env.context.user_data)

        first_reply = _update("yes")
        await text_response_handler(first_reply, env.context)
        assert "read" in first_reply.message.reply_text.await_args.args[0]

        persistence = PostgresPersistence("postgresql+asyncpg://u:p@host:5432/db")

        async def load_stale_user_data(key: str) -> dict:
            return stale_user_data

        monkeypatch.setattr(persistence, "_load_one", load_stale_user_data)
        await persistence.refresh_user_data(TELEGRAM_ID, env.context.user_data)

        final_reply = _update(second_reply)
        await text_response_handler(final_reply, env.context)

        assert "checkin_session" not in env.context.user_data
        assert "check-in complete" in final_reply.message.reply_text.await_args.args[0].lower()

    async def test_skip_is_recorded_as_not_completed(self, env) -> None:
        await _seed(env)
        await checkin_handler(_update(), env.context)

        await text_response_handler(_update("skip"), env.context)
        await _drain_background_tasks(env.app)

        assert "skipped gym" in env.memory.stored[0]["insight"]

    async def test_unrecognised_input_reprompts_instead_of_going_silent(self, env) -> None:
        await _seed(env)
        await checkin_handler(_update(), env.context)

        reply = _update("maybe later")
        await text_response_handler(reply, env.context)

        reply.message.reply_text.assert_awaited_once()
        assert "didn't catch that" in reply.message.reply_text.await_args.args[0]
        assert "checkin_session" in env.context.user_data

    async def test_text_outside_a_checkin_is_ignored(self, env) -> None:
        await _seed(env)
        reply = _update("hello")

        await text_response_handler(reply, env.context)

        reply.message.reply_text.assert_not_awaited()

    async def test_corrupt_session_is_dropped_rather_than_trapping_the_user(self, env) -> None:
        """A session persisted by an older release must not wedge the check-in."""
        await _seed(env)
        env.context.user_data["checkin_session"] = {"user_id": 1}  # missing keys

        reply = _update("yes")
        await text_response_handler(reply, env.context)

        assert "checkin_session" not in env.context.user_data
        reply.message.reply_text.assert_not_awaited()

    async def test_checkin_recovers_from_a_corrupt_session(self, env) -> None:
        """/checkin decoded the stored session unguarded and raised on a bad one."""
        await _seed(env)
        env.context.user_data["checkin_session"] = {"user_id": 1}  # missing keys

        update = _update()
        await checkin_handler(update, env.context)

        assert "gym" in update.message.reply_text.await_args.args[0]
        assert env.context.user_data["checkin_session"]["habits"]

    async def test_expired_session_is_replaced_by_a_fresh_one(self, env) -> None:
        await _seed(env)
        await checkin_handler(_update(), env.context)
        stale = env.context.user_data["checkin_session"]
        stale["created_at"] = (datetime.now(UTC) - timedelta(hours=TTL_HOURS + 1)).isoformat()

        update = _update()
        await checkin_handler(update, env.context)

        assert "gym" in update.message.reply_text.await_args.args[0]
        assert env.context.user_data["checkin_session"]["created_at"] != stale["created_at"]

    async def test_proof_habit_asks_for_proof_before_completing(self, env) -> None:
        await _seed(env, policy=VerificationPolicy.TEXT)
        await checkin_handler(_update(), env.context)

        reply = _update("yes")
        await text_response_handler(reply, env.context)

        assert "proof" in reply.message.reply_text.await_args.args[0].lower()
        assert env.context.user_data["checkin_session"]["state"] == "awaiting_proof"
        assert env.memory.stored == []

    async def test_proof_habit_completes_after_proof_is_verified(self, env) -> None:
        await _seed(env, policy=VerificationPolicy.TEXT)
        await checkin_handler(_update(), env.context)
        await text_response_handler(_update("yes"), env.context)

        await text_response_handler(_update("I ran 5km this morning"), env.context)
        await _drain_background_tasks(env.app)

        assert "checkin_session" not in env.context.user_data
        assert "completed gym" in env.memory.stored[0]["insight"]
