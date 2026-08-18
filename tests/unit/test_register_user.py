import pytest

from habit_tracker.application.use_cases.register_user import RegisterUser
from habit_tracker.domain.value_objects import TelegramId
from tests.unit.conftest import InMemoryUserRepository


@pytest.fixture
def user_repo():
    return InMemoryUserRepository()


class TestRegisterUser:
    async def test_new_user(self, user_repo):
        uc = RegisterUser(user_repo)
        user, is_new = await uc.execute(TelegramId(123), "alice")
        assert is_new is True
        assert user.telegram_id == TelegramId(123)
        assert user.username == "alice"
        assert user.id is not None

    async def test_existing_user(self, user_repo):
        uc = RegisterUser(user_repo)
        await uc.execute(TelegramId(123), "alice")
        user, is_new = await uc.execute(TelegramId(123))
        assert is_new is False
        assert user.username == "alice"
