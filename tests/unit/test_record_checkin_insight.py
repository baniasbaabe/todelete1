"""Tests for the memory write path.

Before this use case existed, ``MemoryStore.store_insight`` had no production
caller, so ``get_insights`` always returned an empty list and every coaching
message was generated blind. These tests pin the write half in place.
"""

from __future__ import annotations

from datetime import UTC, datetime

from habit_tracker.application.checkin_session import CheckinResult
from habit_tracker.application.use_cases.record_checkin_insight import (
    INSIGHT_CATEGORY,
    RecordCheckinInsight,
)
from tests.unit.conftest import FakeMemoryStore

OCCURRED_AT = datetime(2026, 3, 14, 9, 30, tzinfo=UTC)


def _result(name: str, *, completed: bool) -> CheckinResult:
    return CheckinResult(habit_name=name, completed=completed, skipped=not completed)


class TestRecordCheckinInsight:
    async def test_stores_completed_and_skipped_habits(self) -> None:
        memory = FakeMemoryStore()

        await RecordCheckinInsight(memory).execute(
            user_id=7,
            results=[_result("gym", completed=True), _result("read", completed=False)],
            occurred_at=OCCURRED_AT,
        )

        assert len(memory.stored) == 1
        insight = memory.stored[0]["insight"]
        assert "completed gym" in insight
        assert "skipped read" in insight
        assert "2026-03-14" in insight

    async def test_stores_under_the_given_user_id_and_category(self) -> None:
        memory = FakeMemoryStore()

        await RecordCheckinInsight(memory).execute(
            user_id=42, results=[_result("gym", completed=True)], occurred_at=OCCURRED_AT
        )

        assert memory.stored[0]["user_id"] == 42
        assert memory.stored[0]["category"] == INSIGHT_CATEGORY

    async def test_written_insight_is_readable_back(self) -> None:
        """The write and read halves must agree on the user ID namespace."""
        memory = FakeMemoryStore()

        await RecordCheckinInsight(memory).execute(
            user_id=99, results=[_result("gym", completed=True)], occurred_at=OCCURRED_AT
        )

        assert [i.content for i in await memory.get_insights(99)] == [memory.stored[0]["insight"]]
        assert await memory.get_insights(100) == []

    async def test_omits_empty_clauses(self) -> None:
        memory = FakeMemoryStore()

        await RecordCheckinInsight(memory).execute(
            user_id=1,
            results=[_result("gym", completed=True), _result("run", completed=True)],
            occurred_at=OCCURRED_AT,
        )

        assert "skipped" not in memory.stored[0]["insight"]

    async def test_empty_session_stores_nothing(self) -> None:
        memory = FakeMemoryStore()

        await RecordCheckinInsight(memory).execute(user_id=1, results=[], occurred_at=OCCURRED_AT)

        assert memory.stored == []
