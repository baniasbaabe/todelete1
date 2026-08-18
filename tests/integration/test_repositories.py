from __future__ import annotations

from datetime import UTC, datetime, timedelta
import random

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.domain.entities.completion import Completion
from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.entities.user import User
from habit_tracker.domain.exceptions import (
    CompletionNotFoundError,
    HabitAlreadyExistsError,
    HabitNotFoundError,
    UserNotFoundError,
)
from habit_tracker.domain.value_objects.frequency import Frequency
from habit_tracker.domain.value_objects.habit_name import HabitName
from habit_tracker.domain.value_objects.telegram_id import TelegramId
from habit_tracker.domain.value_objects.verification_policy import ProofType, VerificationPolicy
from habit_tracker.infrastructure.database.repositories import (
    SQLAlchemyCompletionRepository,
    SQLAlchemyHabitRepository,
    SQLAlchemyUserRepository,
)

# ── Helpers ────────────────────────────────────────────────────────────────────


def make_user(telegram_id: int = 123456789, username: str | None = "testuser") -> User:
    return User.create(TelegramId(telegram_id), username)


def make_habit(user_id: int, name: str = "Exercise") -> Habit:
    return Habit.create(
        user_id=user_id,
        name=HabitName(name),
        description="Daily exercise",
        frequency=Frequency.DAILY,
        verification_policy=VerificationPolicy.TEXT,
    )


def make_completion(habit_id: int, verified: bool = True) -> Completion:
    return Completion.create(
        habit_id=habit_id,
        proof_type=ProofType.TEXT,
        verified=verified,
        verification_notes="Done!",
    )


# ── User Repository ─────────────────────────────────────────────────────────────


class TestSQLAlchemyUserRepository:
    async def test_save_and_find_by_telegram_id(self, test_session: AsyncSession) -> None:
        repo = SQLAlchemyUserRepository(test_session)
        user = make_user()
        saved = await repo.save(user)

        assert saved.id is not None
        found = await repo.find_by_telegram_id(TelegramId(123456789))
        assert found is not None
        assert found.id == saved.id
        assert found.telegram_id.value == 123456789
        assert found.username == "testuser"

    async def test_find_by_telegram_id_returns_none_for_missing(self, test_session: AsyncSession) -> None:
        repo = SQLAlchemyUserRepository(test_session)
        result = await repo.find_by_telegram_id(TelegramId(999999999))
        assert result is None

    async def test_save_updates_existing_user(self, test_session: AsyncSession) -> None:
        repo = SQLAlchemyUserRepository(test_session)
        user = make_user(telegram_id=111111111, username="original")
        saved = await repo.save(user)
        assert saved.id is not None

        saved.username = "updated"
        updated = await repo.save(saved)
        assert updated.id == saved.id

        found = await repo.find_by_telegram_id(TelegramId(111111111))
        assert found is not None
        assert found.username == "updated"


# ── Habit Repository ────────────────────────────────────────────────────────────


class TestSQLAlchemyHabitRepository:
    async def test_save_and_find_by_id(self, test_session: AsyncSession) -> None:
        user_repo = SQLAlchemyUserRepository(test_session)
        user = await user_repo.save(make_user(telegram_id=200000001))

        habit_repo = SQLAlchemyHabitRepository(test_session)
        habit = make_habit(user_id=user.id)
        saved = await habit_repo.save(habit)

        assert saved.id is not None
        found = await habit_repo.find_by_id(saved.id)
        assert found is not None
        assert found.name.value == "Exercise"
        assert found.frequency == Frequency.DAILY
        assert found.verification_policy == VerificationPolicy.TEXT
        assert found.is_active is True

    async def test_find_active_by_user(self, test_session: AsyncSession) -> None:
        user_repo = SQLAlchemyUserRepository(test_session)
        user = await user_repo.save(make_user(telegram_id=200000002))

        habit_repo = SQLAlchemyHabitRepository(test_session)
        await habit_repo.save(make_habit(user.id, "Running"))
        await habit_repo.save(make_habit(user.id, "Reading"))
        h3 = make_habit(user.id, "Inactive")
        h3_saved = await habit_repo.save(h3)
        h3_saved.deactivate()
        await habit_repo.save(h3_saved)

        active = await habit_repo.find_active_by_user(user.id)
        active_names = {h.name.value for h in active}
        assert "Running" in active_names
        assert "Reading" in active_names
        assert "Inactive" not in active_names

    async def test_find_active_by_user_and_name(self, test_session: AsyncSession) -> None:
        user_repo = SQLAlchemyUserRepository(test_session)
        user = await user_repo.save(make_user(telegram_id=200000003))

        habit_repo = SQLAlchemyHabitRepository(test_session)
        await habit_repo.save(make_habit(user.id, "Meditation"))

        found = await habit_repo.find_active_by_user_and_name(user.id, HabitName("Meditation"))
        assert found is not None
        assert found.name.value == "Meditation"

        not_found = await habit_repo.find_active_by_user_and_name(user.id, HabitName("Nonexistent"))
        assert not_found is None

    async def test_soft_deleted_habit_is_not_found_by_name(self, test_session: AsyncSession) -> None:
        """A deactivated habit must not block re-creating one with the same name."""
        user_repo = SQLAlchemyUserRepository(test_session)
        user = await user_repo.save(make_user(telegram_id=200000009))

        habit_repo = SQLAlchemyHabitRepository(test_session)
        habit = await habit_repo.save(make_habit(user.id, "Journalling"))
        habit.deactivate()
        await habit_repo.save(habit)

        assert await habit_repo.find_active_by_user_and_name(user.id, HabitName("Journalling")) is None

    async def test_delete_habit(self, test_session: AsyncSession) -> None:
        user_repo = SQLAlchemyUserRepository(test_session)
        user = await user_repo.save(make_user(telegram_id=200000004))

        habit_repo = SQLAlchemyHabitRepository(test_session)
        habit = await habit_repo.save(make_habit(user.id, "ToDelete"))
        habit_id = habit.id

        await habit_repo.delete(habit_id)
        found = await habit_repo.find_by_id(habit_id)
        assert found is None

    async def test_find_by_id_returns_none_for_missing(self, test_session: AsyncSession) -> None:
        habit_repo = SQLAlchemyHabitRepository(test_session)
        result = await habit_repo.find_by_id(99999)
        assert result is None


# ── Save semantics ──────────────────────────────────────────────────────────────


class TestSaveRejectsMissingRows:
    """save() on an entity whose row is gone must raise, not silently re-insert.

    Re-inserting handed the caller back a different ID than the one it asked to
    save under, and resurrected rows that had been deleted.
    """

    async def test_habit_save_raises_when_row_is_gone(self, test_session: AsyncSession) -> None:
        user_repo = SQLAlchemyUserRepository(test_session)
        habit_repo = SQLAlchemyHabitRepository(test_session)
        user = await user_repo.save(make_user(telegram_id=411111111))
        habit = await habit_repo.save(make_habit(user.id))
        await habit_repo.delete(habit.id)

        with pytest.raises(HabitNotFoundError):
            await habit_repo.save(habit)

    async def test_user_save_raises_when_row_is_gone(self, test_session: AsyncSession) -> None:
        user_repo = SQLAlchemyUserRepository(test_session)
        ghost = make_user(telegram_id=422222222)
        ghost.id = 987654

        with pytest.raises(UserNotFoundError):
            await user_repo.save(ghost)

    async def test_completion_save_raises_when_row_is_gone(self, test_session: AsyncSession) -> None:
        completion_repo = SQLAlchemyCompletionRepository(test_session)
        ghost = make_completion(habit_id=1)
        ghost.id = 987654

        with pytest.raises(CompletionNotFoundError):
            await completion_repo.save(ghost)


class TestActiveHabitNameUniqueness:
    """The partial unique index backing CreateHabit's duplicate check."""

    async def test_duplicate_active_name_is_rejected(self, test_session: AsyncSession) -> None:
        user_repo = SQLAlchemyUserRepository(test_session)
        habit_repo = SQLAlchemyHabitRepository(test_session)
        user = await user_repo.save(make_user(telegram_id=433333333))
        await habit_repo.save(make_habit(user.id, name="yoga"))

        with pytest.raises(HabitAlreadyExistsError):
            await habit_repo.save(make_habit(user.id, name="yoga"))

    async def test_soft_deleted_name_can_be_reused(self, test_session: AsyncSession) -> None:
        """The index is partial precisely so this keeps working."""
        user_repo = SQLAlchemyUserRepository(test_session)
        habit_repo = SQLAlchemyHabitRepository(test_session)
        user = await user_repo.save(make_user(telegram_id=444444444))
        first = await habit_repo.save(make_habit(user.id, name="yoga"))
        first.deactivate()
        await habit_repo.save(first)

        recreated = await habit_repo.save(make_habit(user.id, name="yoga"))

        assert recreated.id != first.id
        assert recreated.is_active

    async def test_same_name_for_different_users_is_allowed(self, test_session: AsyncSession) -> None:
        user_repo = SQLAlchemyUserRepository(test_session)
        habit_repo = SQLAlchemyHabitRepository(test_session)
        one = await user_repo.save(make_user(telegram_id=455555555))
        two = await user_repo.save(make_user(telegram_id=466666666))

        await habit_repo.save(make_habit(one.id, name="yoga"))
        other = await habit_repo.save(make_habit(two.id, name="yoga"))

        assert other.id is not None


# ── Completion Repository ───────────────────────────────────────────────────────


class TestSQLAlchemyCompletionRepository:
    async def _setup_user_and_habit(self, session: AsyncSession) -> tuple[User, Habit]:
        user_repo = SQLAlchemyUserRepository(session)
        user = await user_repo.save(make_user(telegram_id=random.randint(300000000, 399999999)))
        habit_repo = SQLAlchemyHabitRepository(session)
        habit = await habit_repo.save(make_habit(user.id))
        return user, habit

    async def test_save_and_find_roundtrip(self, test_session: AsyncSession) -> None:
        _, habit = await self._setup_user_and_habit(test_session)
        repo = SQLAlchemyCompletionRepository(test_session)

        completion = make_completion(habit.id)
        saved = await repo.save(completion)

        assert saved.id is not None
        assert saved.habit_id == habit.id
        assert saved.proof_type == ProofType.TEXT
        assert saved.verified is True
        assert saved.verification_notes == "Done!"

    async def test_find_today_by_habits(self, test_session: AsyncSession) -> None:
        _, habit = await self._setup_user_and_habit(test_session)
        repo = SQLAlchemyCompletionRepository(test_session)

        # Save a completion for today
        today_completion = make_completion(habit.id)
        await repo.save(today_completion)

        results = await repo.find_today_by_habits([habit.id])
        assert len(results) >= 1
        assert all(c.habit_id == habit.id for c in results)

    async def test_find_today_by_habits_excludes_old(self, test_session: AsyncSession) -> None:
        _, habit = await self._setup_user_and_habit(test_session)
        repo = SQLAlchemyCompletionRepository(test_session)

        # Old completion (yesterday)
        yesterday = datetime.now(UTC) - timedelta(days=1)
        old = Completion(
            id=None,
            habit_id=habit.id,
            completed_at=yesterday,
            proof_type=ProofType.NONE,
            verified=True,
            verification_notes=None,
        )
        await repo.save(old)

        results = await repo.find_today_by_habits([habit.id])
        assert all(
            c.completed_at >= datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) for c in results
        )

    async def test_find_today_by_habits_empty_list(self, test_session: AsyncSession) -> None:
        repo = SQLAlchemyCompletionRepository(test_session)
        results = await repo.find_today_by_habits([])
        assert results == []

    async def test_get_completion_dates(self, test_session: AsyncSession) -> None:
        _, habit = await self._setup_user_and_habit(test_session)
        repo = SQLAlchemyCompletionRepository(test_session)

        # Add completions on two different days
        now = datetime.now(UTC)
        two_days_ago = now - timedelta(days=2)

        c1 = Completion(
            id=None,
            habit_id=habit.id,
            completed_at=two_days_ago,
            proof_type=ProofType.TEXT,
            verified=True,
            verification_notes=None,
        )
        c2 = Completion(
            id=None,
            habit_id=habit.id,
            completed_at=now,
            proof_type=ProofType.TEXT,
            verified=True,
            verification_notes=None,
        )
        # Duplicate on same day to verify DISTINCT
        c3 = Completion(
            id=None,
            habit_id=habit.id,
            completed_at=now - timedelta(hours=1),
            proof_type=ProofType.TEXT,
            verified=True,
            verification_notes=None,
        )
        for c in [c1, c2, c3]:
            await repo.save(c)

        dates = await repo.get_completion_dates(habit.id)
        # Should be distinct dates, sorted descending
        assert len(dates) == len(set(dates)), "Dates should be deduplicated"
        assert dates == sorted(dates, reverse=True), "Dates should be sorted descending"

    async def test_find_by_habits_since(self, test_session: AsyncSession) -> None:
        _, habit = await self._setup_user_and_habit(test_session)
        repo = SQLAlchemyCompletionRepository(test_session)

        now = datetime.now(UTC)
        old = Completion(
            id=None,
            habit_id=habit.id,
            completed_at=now - timedelta(days=10),
            proof_type=ProofType.NONE,
            verified=True,
            verification_notes=None,
        )
        recent = Completion(
            id=None,
            habit_id=habit.id,
            completed_at=now - timedelta(days=1),
            proof_type=ProofType.NONE,
            verified=True,
            verification_notes=None,
        )
        await repo.save(old)
        await repo.save(recent)

        since = (now - timedelta(days=5)).date()
        grouped = await repo.find_by_habits_since([habit.id], since)

        results = grouped[habit.id]
        assert len(results) == 1
        assert all(c.completed_at >= datetime(since.year, since.month, since.day, tzinfo=UTC) for c in results)

    async def test_batch_queries_return_an_entry_for_every_requested_habit(self, test_session: AsyncSession) -> None:
        """Callers index the result directly, so a habit with no rows must still appear."""
        _, habit = await self._setup_user_and_habit(test_session)
        repo = SQLAlchemyCompletionRepository(test_session)
        missing_id = habit.id + 9999

        dates = await repo.get_completion_dates_by_habits([habit.id, missing_id])
        grouped = await repo.find_by_habits_since([habit.id, missing_id], datetime.now(UTC).date())

        assert dates == {habit.id: [], missing_id: []}
        assert grouped == {habit.id: [], missing_id: []}

    async def test_get_completion_dates_by_habits_separates_habits(self, test_session: AsyncSession) -> None:
        """The batched query must not smear one habit's dates onto another."""
        user, habit_a = await self._setup_user_and_habit(test_session)
        habit_repo = SQLAlchemyHabitRepository(test_session)
        habit_b = await habit_repo.save(Habit.create(user_id=user.id, name=HabitName("second habit")))
        repo = SQLAlchemyCompletionRepository(test_session)

        now = datetime.now(UTC)
        await repo.save(
            Completion(
                id=None,
                habit_id=habit_a.id,
                completed_at=now,
                proof_type=ProofType.NONE,
                verified=True,
                verification_notes=None,
            )
        )
        await repo.save(
            Completion(
                id=None,
                habit_id=habit_b.id,
                completed_at=now - timedelta(days=3),
                proof_type=ProofType.NONE,
                verified=True,
                verification_notes=None,
            )
        )

        dates = await repo.get_completion_dates_by_habits([habit_a.id, habit_b.id])

        assert dates[habit_a.id] == [now.date()]
        assert dates[habit_b.id] == [(now - timedelta(days=3)).date()]

    async def test_get_completion_dates_by_habits_is_newest_first(self, test_session: AsyncSession) -> None:
        _, habit = await self._setup_user_and_habit(test_session)
        repo = SQLAlchemyCompletionRepository(test_session)

        now = datetime.now(UTC)
        for offset in (5, 1, 3):
            await repo.save(
                Completion(
                    id=None,
                    habit_id=habit.id,
                    completed_at=now - timedelta(days=offset),
                    proof_type=ProofType.NONE,
                    verified=True,
                    verification_notes=None,
                )
            )

        dates = (await repo.get_completion_dates_by_habits([habit.id]))[habit.id]

        assert dates == sorted(dates, reverse=True)
