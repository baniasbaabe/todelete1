import pytest

from habit_tracker.application.use_cases.create_habit import CreateHabit
from habit_tracker.application.use_cases.register_user import RegisterUser
from habit_tracker.domain.exceptions import HabitAlreadyExistsError, UserNotFoundError
from habit_tracker.domain.value_objects import HabitName, TelegramId, VerificationPolicy
from tests.unit.conftest import InMemoryHabitRepository, InMemoryUserRepository


@pytest.fixture
def repos():
    return InMemoryUserRepository(), InMemoryHabitRepository()


class TestCreateHabit:
    async def test_creates_habit(self, repos):
        user_repo, habit_repo = repos
        await RegisterUser(user_repo).execute(TelegramId(1))
        habit = await CreateHabit(user_repo, habit_repo).execute(TelegramId(1), HabitName("gym"))
        assert habit.name == HabitName("gym")
        assert habit.id is not None

    async def test_user_not_found(self, repos):
        user_repo, habit_repo = repos
        with pytest.raises(UserNotFoundError):
            await CreateHabit(user_repo, habit_repo).execute(TelegramId(999), HabitName("gym"))

    async def test_duplicate_name(self, repos):
        user_repo, habit_repo = repos
        await RegisterUser(user_repo).execute(TelegramId(1))
        uc = CreateHabit(user_repo, habit_repo)
        await uc.execute(TelegramId(1), HabitName("gym"))
        with pytest.raises(HabitAlreadyExistsError):
            await uc.execute(TelegramId(1), HabitName("gym"))

    async def test_with_verification_policy(self, repos):
        user_repo, habit_repo = repos
        await RegisterUser(user_repo).execute(TelegramId(1))
        habit = await CreateHabit(user_repo, habit_repo).execute(
            TelegramId(1),
            HabitName("gym"),
            verification_policy=VerificationPolicy.PHOTO,
        )
        assert habit.verification_policy == VerificationPolicy.PHOTO
