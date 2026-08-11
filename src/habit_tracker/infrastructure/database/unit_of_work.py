from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.application.ports.repositories import (
    CompletionRepository,
    HabitRepository,
    UserRepository,
)
from habit_tracker.infrastructure.database.connection import DatabaseSessionManager
from habit_tracker.infrastructure.database.repositories.completion_repository import (
    SQLAlchemyCompletionRepository,
)
from habit_tracker.infrastructure.database.repositories.habit_repository import (
    SQLAlchemyHabitRepository,
)
from habit_tracker.infrastructure.database.repositories.user_repository import (
    SQLAlchemyUserRepository,
)


@dataclass(frozen=True)
class UnitOfWork:
    """Every repository bound to a single transaction."""

    users: UserRepository
    habits: HabitRepository
    completions: CompletionRepository
    session: AsyncSession

    async def commit(self) -> None:
        await self.session.commit()


@asynccontextmanager
async def open_unit_of_work(db: DatabaseSessionManager) -> AsyncGenerator[UnitOfWork]:
    """Open a transaction with all repositories sharing its session.

    Nothing is persisted unless ``commit()`` is called, and the session rolls
    back on any exception leaving the block.
    """
    async with db.session() as session:
        yield UnitOfWork(
            users=SQLAlchemyUserRepository(session),
            habits=SQLAlchemyHabitRepository(session),
            completions=SQLAlchemyCompletionRepository(session),
            session=session,
        )
