from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
from typing import Any

import asyncpg
import structlog
from telegram.ext import BasePersistence, PersistenceInput

from habit_tracker.infrastructure.database.connection import verified_ssl_context
from habit_tracker.infrastructure.resilience import retry_store

logger = structlog.get_logger()


class PostgresPersistence(BasePersistence):
    """Persists python-telegram-bot state in the bot_persistence table.

    Each user and chat gets its own row (user_data:{id}, chat_data:{id}).
    Concurrent update_user_data calls for different users now touch disjoint
    rows, eliminating the read-modify-write race that the single-blob design
    suffered when two check-ins arrived simultaneously.

    The table is created by the Alembic revision that introduced it, not here:
    the runtime role (habit_app) deliberately holds no DDL rights on the public
    schema, so a compromise of this container cannot rewrite the schema.
    """

    def __init__(self, database_url: str) -> None:
        super().__init__(
            # bot_data holds live service objects (engines, clients, pools). Storing
            # it would both JSON-serialise them into junk on write and overwrite them
            # with that junk on the next startup, so it stays off. Check-in sessions
            # live in user_data, which is plain JSON-safe dicts.
            store_data=PersistenceInput(
                bot_data=False,
                chat_data=True,
                user_data=True,
                callback_data=False,
            ),
        )
        # Convert asyncpg URL to raw postgresql for asyncpg direct connection
        url = database_url.replace("postgresql+asyncpg://", "postgresql://")
        # Strip libpq query params: asyncpg would treat sslmode as a connect
        # kwarg. TLS is supplied as an explicit verified SSLContext below.
        self._database_url = url.split("?", 1)[0]
        self._pool = None
        # Same idiom as Mem0MemoryStore._client(): without it two concurrent
        # first-callers can each build a pool and orphan one, leaking its
        # connections for the life of the process.
        self._pool_lock = asyncio.Lock()

    async def _get_pool(self):
        async with self._pool_lock:
            if self._pool is None:
                self._pool = await self._create_pool()
            return self._pool

    async def _create_pool(self):
        # Without this, asyncpg defaults to sslmode=prefer: opportunistic
        # TLS that silently falls back to plaintext if the server declines,
        # exposing credentials and every persisted check-in session.
        ssl_context = None
        if ".database.azure.com" in self._database_url:
            ssl_context = verified_ssl_context()

        return await asyncpg.create_pool(
            self._database_url,
            min_size=1,
            max_size=3,
            ssl=ssl_context,
        )

    @retry_store()
    async def _load_one(self, key: str) -> dict:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT data FROM bot_persistence WHERE key = $1", key)
            if row:
                data = row["data"]
                return json.loads(data) if isinstance(data, str) else data
            return {}

    @retry_store()
    async def _load_prefixed(self, prefix: str) -> dict[int, dict]:
        """Fetch all rows whose key begins with the given prefix.

        The prefix carries no trailing colon -- pass "user_data", not
        "user_data:"; the separator is appended below. A caller that includes it
        builds the pattern 'user!_data::%', matches nothing, and gets an empty
        mapping with no error.

        Returns a mapping of integer IDs to their stored dicts so that
        callers see the same shape as before but reads are now per-row.
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # Escape _ so the LIKE pattern treats it as a literal character, not
            # a single-character wildcard (user_data: would otherwise match
            # userXdata: etc.).
            escaped = prefix.replace("_", "!_")
            rows = await conn.fetch(
                "SELECT key, data FROM bot_persistence WHERE key LIKE $1 ESCAPE '!'",
                f"{escaped}:%",
            )
            result = {}
            for row in rows:
                suffix = row["key"].split(":", 1)[1]
                try:
                    user_id = int(suffix)
                except ValueError:
                    # A non-integer suffix means the row was written by an older
                    # schema or corrupted. Skip rather than crash Application.initialize().
                    logger.warning("skipping row with non-integer key suffix", key=row["key"])
                    continue
                data = row["data"]
                result[user_id] = json.loads(data) if isinstance(data, str) else data
            return result

    @retry_store()
    async def _save(self, key: str, data: dict) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO bot_persistence (key, data, updated_at) VALUES ($1, $2::jsonb, $3)
                ON CONFLICT (key) DO UPDATE SET data = $2::jsonb, updated_at = $3
            """,
                key,
                json.dumps(data, default=str),
                datetime.now(UTC),
            )

    @retry_store()
    async def _delete(self, key: str) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM bot_persistence WHERE key = $1", key)

    # Required BasePersistence methods
    async def get_bot_data(self) -> dict:
        return await self._load_one("bot_data")

    async def update_bot_data(self, data: dict) -> None:
        await self._save("bot_data", data)

    async def refresh_bot_data(self, bot_data: dict) -> None:
        # PTB discards the return value and requires in-place mutation so the
        # caller's reference sees the updated state after process_update().
        fresh = await self._load_one("bot_data")
        bot_data.clear()
        bot_data.update(fresh)

    async def get_chat_data(self) -> dict[int, dict]:
        return await self._load_prefixed("chat_data")

    async def update_chat_data(self, chat_id: int, data: dict) -> None:
        await self._save(f"chat_data:{chat_id}", data)

    async def refresh_chat_data(self, chat_id: int, chat_data: dict) -> None:
        fresh = await self._load_one(f"chat_data:{chat_id}")
        chat_data.clear()
        chat_data.update(fresh)

    async def get_user_data(self) -> dict[int, dict]:
        return await self._load_prefixed("user_data")

    async def update_user_data(self, user_id: int, data: dict) -> None:
        await self._save(f"user_data:{user_id}", data)

    async def refresh_user_data(self, user_id: int, user_data: dict) -> None:
        """Keep PTB's live user data authoritative between periodic writes.

        PTB invokes this hook before every handler but writes persistence on a
        timer. Reloading here can therefore replace a just-advanced check-in
        with the older database copy before the next reply is processed.
        """

    async def get_callback_data(self) -> Any:
        return None

    async def update_callback_data(self, data: Any) -> None:
        pass

    async def get_conversations(self, name: str) -> dict:
        return {}

    async def update_conversation(self, name: str, key: tuple, new_state: Any) -> None:
        pass

    async def drop_chat_data(self, chat_id: int) -> None:
        await self._delete(f"chat_data:{chat_id}")

    async def drop_user_data(self, user_id: int) -> None:
        await self._delete(f"user_data:{user_id}")

    async def flush(self) -> None:
        pass

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
