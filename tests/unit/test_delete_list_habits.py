from __future__ import annotations

import pytest

from habit_tracker.application.use_cases.create_habit import CreateHabit
from habit_tracker.application.use_cases.delete_habit import DeleteHabit
from habit_tracker.application.use_cases.list_habits import ListHabits
from habit_tracker.application.use_cases.register_user import RegisterUser
from habit_tracker.domain.exceptions import HabitNotFoundError, UserNotFoundError
from habit_tracker.domain.value_objects import HabitName, TelegramId
from tests.unit.conftest import (
    InMemoryCompletionRepository,
    InMemoryHabitRepository,
    InMemoryUserRepository,
)

TELEGRAM_ID = TelegramId(42)


@pytest.fixture
def repos():
    return InMemoryUserRepository(), InMemoryHabitRepository()


@pytest.fixture
def full_repos():
    return InMemoryUserRepository(), InMemoryHabitRepository(), InMemoryCompletionRepository()


class TestDeleteHabit:
    async def test_deactivates_habit(self, repos):
        user_repo, habit_repo = repos
        await RegisterUser(user_repo).execute(TELEGRAM_ID)
        await CreateHabit(user_repo, habit_repo).execute(TELEGRAM_ID, HabitName("yoga"))

        await DeleteHabit(user_repo, habit_repo).execute(TELEGRAM_ID, HabitName("yoga"))

        active = await habit_repo.find_active_by_user(1)
        assert active == []

    async def test_deleted_habit_name_can_be_reused(self, repos):
        """Soft delete must not permanently reserve the name."""
        user_repo, habit_repo = repos
        await RegisterUser(user_repo).execute(TELEGRAM_ID)
        await CreateHabit(user_repo, habit_repo).execute(TELEGRAM_ID, HabitName("yoga"))
        await DeleteHabit(user_repo, habit_repo).execute(TELEGRAM_ID, HabitName("yoga"))

        recreated = await CreateHabit(user_repo, habit_repo).execute(TELEGRAM_ID, HabitName("yoga"))

        assert recreated.is_active
        active = await habit_repo.find_active_by_user(1)
        assert [h.name.value for h in active] == ["yoga"]

    async def test_deleting_twice_raises_not_found(self, repos):
        user_repo, habit_repo = repos
        await RegisterUser(user_repo).execute(TELEGRAM_ID)
        await CreateHabit(user_repo, habit_repo).execute(TELEGRAM_ID, HabitName("yoga"))
        await DeleteHabit(user_repo, habit_repo).execute(TELEGRAM_ID, HabitName("yoga"))

        with pytest.raises(HabitNotFoundError):
            await DeleteHabit(user_repo, habit_repo).execute(TELEGRAM_ID, HabitName("yoga"))

    async def test_habit_not_found_raises_error(self, repos):
        user_repo, habit_repo = repos
        await RegisterUser(user_repo).execute(TELEGRAM_ID)

        with pytest.raises(HabitNotFoundError):
            await DeleteHabit(user_repo, habit_repo).execute(TELEGRAM_ID, HabitName("nonexistent"))

    async def test_user_not_found_raises_error(self, repos):
        user_repo, habit_repo = repos

        with pytest.raises(UserNotFoundError):
            await DeleteHabit(user_repo, habit_repo).execute(TelegramId(999), HabitName("yoga"))


class TestListHabits:
    async def test_returns_habits_with_streaks(self, full_repos):
        user_repo, habit_repo, completion_repo = full_repos
        await RegisterUser(user_repo).execute(TELEGRAM_ID)
        await CreateHabit(user_repo, habit_repo).execute(TELEGRAM_ID, HabitName("run"))
        await CreateHabit(user_repo, habit_repo).execute(TELEGRAM_ID, HabitName("read"))

        results = await ListHabits(user_repo, habit_repo, completion_repo).execute(TELEGRAM_ID)

        assert len(results) == 2
        habit_names = {r[0].name.value for r in results}
        assert habit_names == {"run", "read"}
        # All streaks should be zero since no completions recorded
        for _, streak in results:
            assert streak.current == 0

    async def test_empty_when_no_habits(self, full_repos):
        user_repo, habit_repo, completion_repo = full_repos
        await RegisterUser(user_repo).execute(TELEGRAM_ID)

        results = await ListHabits(user_repo, habit_repo, completion_repo).execute(TELEGRAM_ID)

        assert results == []

    async def test_user_not_found_raises_error(self, full_repos):
        user_repo, habit_repo, completion_repo = full_repos

        with pytest.raises(UserNotFoundError):
            await ListHabits(user_repo, habit_repo, completion_repo).execute(TelegramId(999))
