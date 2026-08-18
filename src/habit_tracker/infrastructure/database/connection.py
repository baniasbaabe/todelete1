from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import ssl

import certifi
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_ASYNC_DRIVER = "postgresql+asyncpg"
_SYNC_DRIVERS = ("postgres", "postgresql", "postgresql+psycopg2")


def _normalize_url(database_url: str) -> URL:
    """Coerce a PostgreSQL URL into one create_async_engine can actually use.

    Two things go wrong with a URL taken straight from DATABASE_URL:

    1. A bare ``postgresql://`` scheme resolves to the sync psycopg2 dialect,
       and create_async_engine rejects it with "The asyncio extension requires
       an async driver".
    2. SQLAlchemy forwards unrecognised query parameters to ``asyncpg.connect()``
       as keyword arguments. libpq parameters such as ``sslmode`` are not
       asyncpg kwargs, so they raise TypeError. TLS is configured through an
       explicit SSLContext instead.
    """
    url = make_url(database_url)
    if url.drivername in _SYNC_DRIVERS:
        url = url.set(drivername=_ASYNC_DRIVER)
    return url.set(query={k: v for k, v in url.query.items() if not k.startswith("ssl")})


def verified_ssl_context() -> ssl.SSLContext:
    """TLS context that authenticates the server, not just encrypts the channel.

    asyncpg maps the string ``"require"`` onto libpq semantics, which disable
    hostname checking and set verify_mode to CERT_NONE — encrypted but
    unauthenticated, so any presented certificate is accepted.
    """
    context = ssl.create_default_context(cafile=certifi.where())
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def _connect_args_for(url: URL) -> dict:
    """Require verified TLS for Azure; leave local development unencrypted."""
    if url.host and url.host.endswith(".database.azure.com"):
        return {"ssl": verified_ssl_context()}
    return {}


class DatabaseSessionManager:
    def __init__(self, database_url: str) -> None:
        url = _normalize_url(database_url)
        connect_args = _connect_args_for(url)

        self._engine = create_async_engine(
            url,
            pool_size=5,
            max_overflow=10,
            connect_args=connect_args,
        )
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession]:
        async with self._session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    async def close(self) -> None:
        await self._engine.dispose()
