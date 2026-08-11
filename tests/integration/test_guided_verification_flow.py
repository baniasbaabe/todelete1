"""Repository-backed guided verification journeys through Telegram handlers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession
from telegram.ext import ApplicationBuilder

from habit_tracker.domain.entities.completion import Completion
from habit_tracker.domain.value_objects import TelegramId
from habit_tracker.domain.value_objects.verification_policy import ProofType, VerificationPolicy
from habit_tracker.infrastructure.database.connection import DatabaseSessionManager
from habit_tracker.infrastructure.database.repositories import (
    SQLAlchemyCompletionRepository,
    SQLAlchemyHabitRepository,
    SQLAlchemyUserRepository,
)
from habit_tracker.infrastructure.database.unit_of_work import UnitOfWork
from habit_tracker.presentation.dependencies import Dependencies, install
from habit_tracker.presentation.handlers.checkin_handlers import checkin_handler
from habit_tracker.presentation.handlers.command_handlers import add_habit_handler, start_handler
from habit_tracker.presentation.handlers.proof_handlers import photo_response_handler, text_response_handler
from tests.unit.conftest import (
    FakeMemoryStore,
    FakePatternAnalyzer,
    FakeProofVerifier,
    FakeVerificationRecommender,
)

TELEGRAM_ID = 314159


class _RepositoryDependencies(Dependencies):
    """Bind every handler unit of work to the isolated integration session."""

    _session: AsyncSession

    def __init__(self, session: AsyncSession, recommendation: VerificationPolicy) -> None:
        super().__init__(
            db=cast(DatabaseSessionManager, SimpleNamespace()),
            proof_verifier=FakeProofVerifier(result_verified=True),
            memory_store=FakeMemoryStore(),
            pattern_analyzer=FakePatternAnalyzer(),
            verification_recommender=FakeVerificationRecommender(recommendation),
        )
        object.__setattr__(self, "_session", session)

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncGenerator[UnitOfWork]:
        yield UnitOfWork(
            users=SQLAlchemyUserRepository(self._session),
            habits=SQLAlchemyHabitRepository(self._session),
            completions=SQLAlchemyCompletionRepository(self._session),
            session=self._session,
        )


def _context(session: AsyncSession, recommendation: VerificationPolicy) -> SimpleNamespace:
    app = ApplicationBuilder().token("123:ABC").build()
    install(app, _RepositoryDependencies(session, recommendation))
    downloaded_file = SimpleNamespace(download_as_bytearray=AsyncMock(return_value=bytearray(b"photo proof")))
    bot = SimpleNamespace(get_file=AsyncMock(return_value=downloaded_file))
    return SimpleNamespace(application=app, user_data={}, bot=bot)


def _update(text: str | None = None, *, with_photo: bool = False) -> SimpleNamespace:
    photos = [SimpleNamespace(file_id="largest-photo")] if with_photo else []
    message = SimpleNamespace(text=text, reply_text=AsyncMock(), photo=photos)
    user = SimpleNamespace(id=TELEGRAM_ID, username="integration-tester")
    return SimpleNamespace(message=message, effective_user=user)


async def _drain_background_tasks() -> None:
    """Let the final fire-and-forget memory write finish before teardown."""
    for _ in range(5):
        await asyncio.sleep(0)


async def _persisted_journey_result(
    test_session: AsyncSession,
) -> tuple[VerificationPolicy, list[Completion]]:
    users = SQLAlchemyUserRepository(test_session)
    user = await users.find_by_telegram_id(TelegramId(TELEGRAM_ID))
    assert user is not None
    assert user.id is not None

    habits = await SQLAlchemyHabitRepository(test_session).find_active_by_user(user.id)
    assert len(habits) == 1
    habit = habits[0]
    assert habit.id is not None
    completions = await SQLAlchemyCompletionRepository(test_session).find_today_by_habits([habit.id])
    return habit.verification_policy, completions


async def test_photo_recommendation_completes_repository_backed_journey(test_session: AsyncSession) -> None:
    context = _context(test_session, VerificationPolicy.PHOTO)

    await start_handler(_update("/start"), context)
    await add_habit_handler(_update("/add_habit Gym"), context)
    await text_response_handler(_update("yes"), context)
    await checkin_handler(_update("/checkin"), context)
    await text_response_handler(_update("yes"), context)
    await photo_response_handler(_update(with_photo=True), context)
    await _drain_background_tasks()

    policy, completions = await _persisted_journey_result(test_session)
    assert policy is VerificationPolicy.PHOTO
    assert len(completions) == 1
    assert completions[0].verified is True
    assert completions[0].proof_type is ProofType.PHOTO
    assert "checkin_session" not in context.user_data


async def test_quiz_recommendation_completes_repository_backed_journey(test_session: AsyncSession) -> None:
    context = _context(test_session, VerificationPolicy.QUIZ)

    await start_handler(_update("/start"), context)
    await add_habit_handler(_update("/add_habit Learn Python"), context)
    await text_response_handler(_update("yes"), context)
    await checkin_handler(_update("/checkin"), context)
    await text_response_handler(_update("yes"), context)
    await text_response_handler(_update("async context managers"), context)
    await text_response_handler(_update("They await setup and cleanup around a block."), context)
    await _drain_background_tasks()

    policy, completions = await _persisted_journey_result(test_session)
    assert policy is VerificationPolicy.QUIZ
    assert len(completions) == 1
    assert completions[0].verified is True
    assert completions[0].proof_type is ProofType.QUIZ
    assert "checkin_session" not in context.user_data
