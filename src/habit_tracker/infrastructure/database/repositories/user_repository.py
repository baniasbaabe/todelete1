from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.domain.entities.user import User
from habit_tracker.domain.exceptions import UserNotFoundError
from habit_tracker.domain.value_objects.telegram_id import TelegramId
from habit_tracker.infrastructure.database.models import UserModel


class SQLAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, user: User) -> User:
        """Insert a new user or update an existing one.

        A missing row for a given ID raises rather than re-inserting: silently
        recreating it would hand the caller a different ID than the one it
        asked to save under.
        """
        if user.id is None:
            model = self._to_model(user)
            self._session.add(model)
        else:
            model = await self._session.get(UserModel, user.id)
            if model is None:
                raise UserNotFoundError(f"User {user.id} no longer exists")
            model.telegram_id = user.telegram_id.value
            model.username = user.username
            model.created_at = user.created_at

        await self._session.flush()
        user.id = model.id
        return user

    async def find_by_telegram_id(self, telegram_id: TelegramId) -> User | None:
        stmt = select(UserModel).where(UserModel.telegram_id == telegram_id.value)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_entity(model)

    def _to_entity(self, model: UserModel) -> User:
        return User(
            id=model.id,
            telegram_id=TelegramId(model.telegram_id),
            username=model.username,
            created_at=model.created_at,
        )

    def _to_model(self, user: User) -> UserModel:
        return UserModel(
            telegram_id=user.telegram_id.value,
            username=user.username,
            created_at=user.created_at,
        )
