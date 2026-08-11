"""Unit tests for the resilience module (retry decorators)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import groq
import httpx
import psycopg2
import pytest

from habit_tracker.infrastructure.resilience import retry_llm, retry_store


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")


def _response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code, request=_request())


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch asyncio.sleep so retries complete instantly without wall-clock delay."""
    monkeypatch.setattr(asyncio, "sleep", AsyncMock(return_value=None))


class TestRetryLlm:
    async def test_succeeds_on_first_attempt(self) -> None:
        call_count = 0

        @retry_llm()
        async def succeed() -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await succeed()
        assert result == "ok"
        assert call_count == 1

    async def test_retries_on_rate_limit(self) -> None:
        call_count = 0

        @retry_llm()
        async def flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise groq.RateLimitError("rate limited", response=_response(429), body=None)
            return "recovered"

        result = await flaky()
        assert result == "recovered"
        assert call_count == 3

    async def test_retries_on_api_connection_error(self) -> None:
        call_count = 0

        @retry_llm()
        async def flaky_conn() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise groq.APIConnectionError(message="connection refused", request=_request())
            return "connected"

        result = await flaky_conn()
        assert result == "connected"
        assert call_count == 2

    async def test_does_not_retry_auth_error(self) -> None:
        call_count = 0

        @retry_llm()
        async def bad_auth() -> str:
            nonlocal call_count
            call_count += 1
            raise groq.AuthenticationError("bad key", response=_response(401), body=None)

        with pytest.raises(groq.AuthenticationError):
            await bad_auth()

        assert call_count == 1

    async def test_exhausts_retries_reraises(self) -> None:
        call_count = 0

        @retry_llm()
        async def always_fail() -> str:
            nonlocal call_count
            call_count += 1
            raise groq.RateLimitError("rate limited", response=_response(429), body=None)

        with pytest.raises(groq.RateLimitError):
            await always_fail()

        # 3 attempts total (stop_after_attempt(3))
        assert call_count == 3


class TestRetryStore:
    async def test_succeeds_on_first_attempt(self) -> None:
        call_count = 0

        @retry_store()
        async def succeed() -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await succeed()
        assert result == "ok"
        assert call_count == 1

    async def test_retries_on_connection_error(self) -> None:
        call_count = 0

        @retry_store()
        async def flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("connection reset")
            return "recovered"

        result = await flaky()
        assert result == "recovered"
        assert call_count == 2

    async def test_retries_on_os_error(self) -> None:
        call_count = 0

        @retry_store()
        async def flaky_os() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise OSError("broken pipe")
            return "ok"

        result = await flaky_os()
        assert result == "ok"
        assert call_count == 2

    async def test_exhausts_retries_reraises(self) -> None:
        call_count = 0

        @retry_store()
        async def always_fail() -> None:
            nonlocal call_count
            call_count += 1
            raise ConnectionError("connection reset")

        with pytest.raises(ConnectionError):
            await always_fail()

        # 2 attempts total (stop_after_attempt(2))
        assert call_count == 2

    async def test_retries_on_psycopg2_operational_error(self) -> None:
        """mem0's pooled psycopg2 connections raise this, and it is not an OSError.

        The whole point of @retry_store on Mem0MemoryStore: without psycopg2 in
        the predicate the exception is re-raised on the first attempt and the
        insight is silently lost.
        """
        call_count = 0

        @retry_store()
        async def flaky_pg() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise psycopg2.OperationalError("server closed the connection unexpectedly")
            return "recovered"

        result = await flaky_pg()
        assert result == "recovered"
        assert call_count == 2

    async def test_retries_on_psycopg2_interface_error(self) -> None:
        call_count = 0

        @retry_store()
        async def flaky_pg() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise psycopg2.InterfaceError("connection already closed")
            return "recovered"

        result = await flaky_pg()
        assert result == "recovered"
        assert call_count == 2

    async def test_psycopg2_errors_are_not_os_errors(self) -> None:
        """Guards the reason the predicate needs an explicit psycopg2 branch."""
        assert not issubclass(psycopg2.OperationalError, (ConnectionError, OSError, TimeoutError))
        assert not issubclass(psycopg2.InterfaceError, (ConnectionError, OSError, TimeoutError))

    async def test_does_not_retry_psycopg2_programming_error(self) -> None:
        """A bad statement is not transient; retrying it just doubles the damage."""
        call_count = 0

        @retry_store()
        async def bad_sql() -> None:
            nonlocal call_count
            call_count += 1
            raise psycopg2.ProgrammingError("syntax error at or near")

        with pytest.raises(psycopg2.ProgrammingError):
            await bad_sql()

        assert call_count == 1

    async def test_does_not_retry_value_error(self) -> None:
        """Non-transient errors must propagate immediately without retry."""
        call_count = 0

        @retry_store()
        async def bad_value() -> None:
            nonlocal call_count
            call_count += 1
            raise ValueError("domain error")

        with pytest.raises(ValueError):
            await bad_value()

        assert call_count == 1
