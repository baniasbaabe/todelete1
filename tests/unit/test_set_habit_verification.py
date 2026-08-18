import pytest

from habit_tracker.application.use_cases.create_habit import CreateHabit
from habit_tracker.application.use_cases.register_user import RegisterUser
from habit_tracker.application.use_cases.set_habit_verification import SetHabitVerification
from habit_tracker.domain.exceptions import HabitNotFoundError, UserNotFoundError
from habit_tracker.domain.value_objects import HabitName, TelegramId, VerificationPolicy
from tests.unit.conftest import InMemoryHabitRepository, InMemoryUserRepository


async def test_updates_owned_active_habit() -> None:
    users = InMemoryUserRepository()
    habits = InMemoryHabitRepository()
    await RegisterUser(users).execute(TelegramId(111))
    habit = await CreateHabit(users, habits).execute(TelegramId(111), HabitName("Gym"))
    updated = await SetHabitVerification(users, habits).execute(TelegramId(111), habit.id, VerificationPolicy.PHOTO)
    assert updated.verification_policy is VerificationPolicy.PHOTO
    assert (await habits.find_by_id(habit.id)).verification_policy is VerificationPolicy.PHOTO


async def test_rejects_habit_owned_by_another_user() -> None:
    users = InMemoryUserRepository()
    habits = InMemoryHabitRepository()
    await RegisterUser(users).execute(TelegramId(111))
    await RegisterUser(users).execute(TelegramId(222))
    habit = await CreateHabit(users, habits).execute(TelegramId(222), HabitName("Gym"))
    with pytest.raises(HabitNotFoundError):
        await SetHabitVerification(users, habits).execute(TelegramId(111), habit.id, VerificationPolicy.PHOTO)


async def test_rejects_missing_user() -> None:
    with pytest.raises(UserNotFoundError):
        await SetHabitVerification(InMemoryUserRepository(), InMemoryHabitRepository()).execute(
            TelegramId(999), 1, VerificationPolicy.PHOTO
        )


async def test_rejects_missing_habit() -> None:
    users = InMemoryUserRepository()
    await RegisterUser(users).execute(TelegramId(111))
    with pytest.raises(HabitNotFoundError):
        await SetHabitVerification(users, InMemoryHabitRepository()).execute(
            TelegramId(111), 1, VerificationPolicy.PHOTO
        )


async def test_rejects_inactive_habit() -> None:
    users = InMemoryUserRepository()
    habits = InMemoryHabitRepository()
    await RegisterUser(users).execute(TelegramId(111))
    habit = await CreateHabit(users, habits).execute(TelegramId(111), HabitName("Gym"))
    habit.deactivate()
    await habits.save(habit)
    with pytest.raises(HabitNotFoundError):
        await SetHabitVerification(users, habits).execute(TelegramId(111), habit.id, VerificationPolicy.PHOTO)
