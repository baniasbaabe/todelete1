from __future__ import annotations

from habit_tracker.application.ports.repositories import UserRepository
from habit_tracker.domain.entities.user import User
from habit_tracker.domain.value_objects.telegram_id import TelegramId


class RegisterUser:
    def __init__(self, user_repo: UserRepository) -> None:
        self._user_repo = user_repo

    async def execute(self, telegram_id: TelegramId, username: str | None = None) -> tuple[User, bool]:
        existing = await self._user_repo.find_by_telegram_id(telegram_id)
        if existing:
            return existing, False
        user = User.create(telegram_id, username)
        saved = await self._user_repo.save(user)
        return saved, True
