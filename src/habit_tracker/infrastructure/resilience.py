"""Tenacity retry decorators for transient failures in LLM and store calls."""

from __future__ import annotations

import logging

import asyncpg
import groq
import psycopg2
import structlog
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

_logger = structlog.get_logger()
_stdlib_logger = logging.getLogger("habit_tracker.resilience")


def _is_transient_llm_error(exc: BaseException) -> bool:
    """Return True for transient Groq errors that are worth retrying."""
    return isinstance(
        exc,
        (
            groq.RateLimitError,
            groq.APIConnectionError,
            groq.APITimeoutError,
            groq.InternalServerError,
        ),
    )


def retry_llm():
    """Retry decorator factory for LLM API calls.

    3 attempts, 1-10 s exponential backoff with jitter.
    Retries transient failures only; auth and content errors propagate
    immediately.
    """
    return retry(
        retry=retry_if_exception(_is_transient_llm_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=10),
        before_sleep=before_sleep_log(_stdlib_logger, logging.WARNING),
        reraise=True,
    )


def _is_transient_store_error(exc: BaseException) -> bool:
    """Return True for transient store errors that are worth retrying.

    Neither driver's exceptions inherit from ``OSError``: psycopg2's
    ``OperationalError`` and ``InterfaceError`` descend from ``psycopg2.Error``
    -> ``Exception``, and asyncpg's from its own base. So the standard library
    branch below covers neither, and both drivers have to be named explicitly --
    without that, an Azure maintenance blip that drops mem0's pooled connection
    is not retried at all.

    Both drivers are direct runtime dependencies and imported at module scope,
    so exception classification never masks the caller's original error with a
    late import failure.
    """
    if isinstance(exc, (ConnectionError, OSError, TimeoutError)):
        return True

    if isinstance(exc, (asyncpg.PostgresConnectionError, asyncpg.InterfaceError)):
        return True

    # psycopg2.OperationalError also covers authentication failure, so a wrong
    # password costs one extra attempt and ~0.5 s before it surfaces. Accepted
    # deliberately: the alternative is dropping every insight on the first
    # connection blip, which is what this decorator exists to prevent. Do not
    # narrow this to a message match.
    return isinstance(exc, (psycopg2.OperationalError, psycopg2.InterfaceError))


def retry_store():
    """Retry decorator factory for data store calls (mem0, Postgres).

    2 attempts, 0.5-4 s exponential backoff with jitter.  Shorter budget than
    ``retry_llm`` because stores are non-critical -- fail fast and fall back.
    General enough to be reused for any persistence layer (Postgres, Redis, ...).
    """
    return retry(
        retry=retry_if_exception(_is_transient_store_error),
        stop=stop_after_attempt(2),
        wait=wait_exponential_jitter(initial=0.5, max=4),
        before_sleep=before_sleep_log(_stdlib_logger, logging.WARNING),
        reraise=True,
    )
