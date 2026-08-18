from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from habit_tracker.domain.value_objects.telegram_id import TelegramId


@dataclass
class User:
    id: int | None
    telegram_id: TelegramId
    username: str | None
    created_at: datetime

    @classmethod
    def create(cls, telegram_id: TelegramId, username: str | None = None) -> User:
        return cls(
            id=None,
            telegram_id=telegram_id,
            username=username,
            created_at=datetime.now(UTC),
        )
