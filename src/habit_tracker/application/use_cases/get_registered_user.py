from __future__ import annotations

from habit_tracker.application.ports.repositories import UserRepository
from habit_tracker.domain.entities.user import User
from habit_tracker.domain.exceptions import UserNotFoundError
from habit_tracker.domain.value_objects.telegram_id import TelegramId


class GetRegisteredUser:
    """Return the registered application user for a Telegram principal."""

    def __init__(self, user_repo: UserRepository) -> None:
        self._user_repo = user_repo

    async def execute(self, telegram_id: TelegramId) -> User:
        user = await self._user_repo.find_by_telegram_id(telegram_id)
        if user is None or user.id is None:
            raise UserNotFoundError(f"User with telegram_id {telegram_id.value} not found")
        return user
