"""Regression tests for handler dependency wiring.

``Application.initialize()`` reassigns ``bot_data`` from persistence, which
silently discarded everything ``main()`` wired in before startup and left every
handler raising ``KeyError``. These tests pin both halves of the fix: the
persistence flag that stops the overwrite, and the post_init timing.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from telegram.ext import ApplicationBuilder, BasePersistence, PersistenceInput

from habit_tracker.domain.exceptions import ConfigurationError
from habit_tracker.infrastructure.persistence.postgres_persistence import PostgresPersistence
from habit_tracker.presentation.dependencies import Dependencies, dependencies, install
from habit_tracker.presentation.handlers.flow_handlers import (
    interrupt_pending_setup_handler,
    resume_checkin_after_command_handler,
    unknown_command_handler,
)
from habit_tracker.presentation.main import register_handlers
from tests.unit.conftest import FakeVerificationRecommender


class _StubPersistence(BasePersistence):
    """Persistence configured exactly like PostgresPersistence, without a database."""

    def __init__(self, store_data: PersistenceInput) -> None:
        super().__init__(store_data=store_data)
        self.stored: dict = {}

    async def get_bot_data(self):
        return self.stored.get("bot_data", {})

    async def update_bot_data(self, data):
        self.stored["bot_data"] = data

    async def refresh_bot_data(self, bot_data):
        return await self.get_bot_data()

    async def get_chat_data(self):
        return {}

    async def update_chat_data(self, chat_id, data): ...
    async def refresh_chat_data(self, chat_id, chat_data):
        return {}

    async def get_user_data(self):
        return {}

    async def update_user_data(self, user_id, data): ...
    async def refresh_user_data(self, user_id, user_data):
        return {}

    async def get_callback_data(self):
        return None

    async def update_callback_data(self, data): ...
    async def get_conversations(self, name):
        return {}

    async def update_conversation(self, name, key, new_state): ...
    async def drop_chat_data(self, chat_id): ...
    async def drop_user_data(self, user_id): ...
    async def flush(self): ...


def _fake_dependencies() -> Dependencies:
    recommender = FakeVerificationRecommender()
    return Dependencies(
        db=SimpleNamespace(),
        proof_verifier=SimpleNamespace(),
        memory_store=SimpleNamespace(),
        pattern_analyzer=SimpleNamespace(),
        verification_recommender=recommender,
    )


def _context_for(app) -> SimpleNamespace:
    return SimpleNamespace(application=app)


class TestPersistenceConfiguration:
    def test_bot_data_persistence_is_disabled(self) -> None:
        """bot_data holds live engines and clients; persisting it corrupts them."""
        persistence = PostgresPersistence("postgresql+asyncpg://u:p@localhost:5432/db")

        assert persistence.store_data.bot_data is False
        assert persistence.store_data.user_data is True


class TestDependencyWiring:
    async def test_dependencies_survive_persistence_initialization(self) -> None:
        """The exact failure mode: initialize() must not wipe the wiring."""
        persistence = _StubPersistence(
            PersistenceInput(bot_data=False, chat_data=True, user_data=True, callback_data=False)
        )
        app = ApplicationBuilder().token("123:ABC").persistence(persistence).build()
        deps = _fake_dependencies()

        # post_init runs after initialize(), which is what makes this safe.
        await app._initialize_persistence()
        install(app, deps)

        assert dependencies(_context_for(app)) is deps
        assert dependencies(_context_for(app)).verification_recommender is deps.verification_recommender

    async def test_wiring_before_initialization_would_be_lost_if_bot_data_persisted(self) -> None:
        """Guards the reason the flag matters: with bot_data=True the wiring vanishes."""
        persistence = _StubPersistence(
            PersistenceInput(bot_data=True, chat_data=True, user_data=True, callback_data=False)
        )
        app = ApplicationBuilder().token("123:ABC").persistence(persistence).build()

        install(app, _fake_dependencies())
        await app._initialize_persistence()

        with pytest.raises(ConfigurationError, match="missing from bot_data"):
            dependencies(_context_for(app))

    def test_missing_dependencies_raise_a_diagnosable_error(self) -> None:
        app = SimpleNamespace(bot_data={})

        with pytest.raises(ConfigurationError, match="post_init"):
            dependencies(_context_for(app))

    def test_serialised_dependencies_are_rejected(self) -> None:
        """A JSON round trip turns the object into a string; that must not pass silently."""
        app = SimpleNamespace(bot_data={"dependencies": "<Dependencies object at 0x7f00>"})

        with pytest.raises(ConfigurationError, match="Found: str"):
            dependencies(_context_for(app))


def test_command_lifecycle_handlers_surround_normal_commands() -> None:
    app = ApplicationBuilder().token("123:ABC").build()

    register_handlers(app)

    assert [handler.callback for handler in app.handlers[-1]] == [interrupt_pending_setup_handler]
    assert unknown_command_handler in [handler.callback for handler in app.handlers[0]]
    assert [handler.callback for handler in app.handlers[1]] == [resume_checkin_after_command_handler]
