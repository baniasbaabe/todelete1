from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from telegram.ext import ContextTypes

from habit_tracker.application.ports.ai_services import (
    MemoryStore,
    PatternAnalyzer,
    ProofVerifier,
)
from habit_tracker.domain.exceptions import ConfigurationError
from habit_tracker.infrastructure.database.connection import DatabaseSessionManager
from habit_tracker.infrastructure.database.unit_of_work import UnitOfWork, open_unit_of_work

BOT_DATA_KEY = "dependencies"


@dataclass(frozen=True)
class Dependencies:
    """Long-lived services shared by every handler.

    Held under a single ``bot_data`` key rather than one key per service so the
    handlers get a typed object instead of an untyped string-keyed lookup.
    """

    db: DatabaseSessionManager
    proof_verifier: ProofVerifier
    memory_store: MemoryStore
    pattern_analyzer: PatternAnalyzer

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncGenerator[UnitOfWork]:
        async with open_unit_of_work(self.db) as uow:
            yield uow


def install(application, deps: Dependencies) -> None:
    """Publish dependencies to handlers.

    Must run from ``post_init``. ``Application.initialize()`` *reassigns*
    ``bot_data`` from persistence, so anything written before startup is
    discarded — see ``telegram/ext/_application.py``::

        if self.persistence.store_data.bot_data:
            self.bot_data = await self.persistence.get_bot_data()
    """
    application.bot_data[BOT_DATA_KEY] = deps


def dependencies(context: ContextTypes.DEFAULT_TYPE) -> Dependencies:
    """Return the shared services, failing loudly if wiring did not survive startup."""
    deps = context.application.bot_data.get(BOT_DATA_KEY)
    if isinstance(deps, Dependencies):
        return deps
    raise ConfigurationError(
        "Dependencies are missing from bot_data. They must be installed from post_init, "
        "and PersistenceInput(bot_data=...) must stay False so persistence cannot replace "
        f"or serialise them. Found: {type(deps).__name__}."
    )
