"""Mem0-backed implementation of the MemoryStore protocol."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from mem0 import Memory
from mem0.memory import main as mem0_main, telemetry as mem0_telemetry
from mem0.utils.factory import LlmFactory
import structlog

from habit_tracker.application.dtos.memory_dto import MemoryInsight
from habit_tracker.infrastructure.resilience import retry_store

logger = structlog.get_logger()

_MAX_COACHING_INSIGHTS = 20
_GROQ_LLM_CLASS = "habit_tracker.infrastructure.memory.groq_llm.ReasoningDisabledGroqLLM"

_COMPACT_EXTRACTION_PROMPT = """
You extract durable memories from messages.

Return only valid JSON in this shape:
{"memory": [{"id": "0", "text": "...", "linked_memory_ids": []}]}

Rules:
- Extract facts only from New Messages. Use earlier messages and existing memories only to resolve context and avoid duplicates.
- Write self-contained factual memories of at most 40 words each.
- Skip facts already represented by an existing memory unless the new message records a new event or meaningful change.
- For a related new event or change, include the relevant Existing Memory IDs in linked_memory_ids.
- Do not invent details. If there is nothing durable to store, return {"memory": []}.
""".strip()


def _configure_mem0_telemetry(enabled: bool) -> None:
    """Apply the injected policy to every telemetry state copied by Mem0."""
    mem0_telemetry.MEM0_TELEMETRY = enabled
    mem0_main.MEM0_TELEMETRY = enabled

    if enabled:
        return

    # Mem0 initializes its hosted-client telemetry when imported and lazily
    # initializes OSS telemetry. Close either client so disabling telemetry via
    # Settings also stops clients that existed before application startup.
    mem0_telemetry.client_telemetry.close()
    if mem0_telemetry._oss_telemetry_instance is not None:
        mem0_telemetry._oss_telemetry_instance.close()
        mem0_telemetry._oss_telemetry_instance = None  # pyrefly: ignore[bad-assignment]


class Mem0MemoryStore:
    """Wraps mem0.Memory to implement the MemoryStore protocol.

    The client is built on first use, not in ``__init__``. ``from_config``
    opens a connection to the vector store, so building it eagerly meant a
    pgvector outage at boot took the whole bot down with it — long-term memory
    is an enhancement to coaching, not a reason to stop tracking habits.
    """

    def __init__(self, config: dict, *, telemetry_enabled: bool = False) -> None:
        # Keep telemetry policy explicit and injectable rather than mutating
        # process environment from library code.
        _configure_mem0_telemetry(telemetry_enabled)

        # Mem0 2.0.13's generic additive extraction prompt is about 5,000
        # words. It alone nearly exhausts Groq's on-demand TPM limit. The input
        # here is already concise, so use a schema-compatible base prompt while
        # retaining infer=True and deduplication. Domain policy is supplied via
        # Mem0's supported custom_instructions configuration.
        mem0_main.ADDITIVE_EXTRACTION_PROMPT = _COMPACT_EXTRACTION_PROMPT
        LlmFactory.register_provider("groq", _GROQ_LLM_CLASS)

        self._memory_cls = Memory
        self._config = config
        self._memory: Any | None = None
        self._lock = asyncio.Lock()

    async def _client(self) -> Any:
        """Return the mem0 client, connecting on first use.

        Failures are deliberately not cached: a vector store that was down at
        boot should start working again without restarting the bot.
        """
        async with self._lock:
            if self._memory is None:
                self._memory = await asyncio.to_thread(self._memory_cls.from_config, self._config)
            return self._memory

    async def store_insight(self, user_id: int, insight: str, category: str) -> None:
        """Persist an insight for the given user, tagged with a category."""
        try:
            await self._store_insight_inner(user_id, insight, category)
        except Exception:
            logger.exception("mem0_store_error", user_id=user_id)

    @retry_store()
    async def _store_insight_inner(self, user_id: int, insight: str, category: str) -> None:
        memory = await self._client()
        await asyncio.to_thread(
            memory.add,
            insight,
            user_id=str(user_id),
            metadata={"category": category},
            infer=True,
        )

    async def get_insights(self, user_id: int) -> list[MemoryInsight]:
        """Return a bounded set of stored insights for the given user."""
        try:
            return await self._get_insights_inner(user_id)
        except Exception:
            logger.exception("mem0_get_error", user_id=user_id)
            return []

    @retry_store()
    async def _get_insights_inner(self, user_id: int) -> list[MemoryInsight]:
        memory = await self._client()
        results = await asyncio.to_thread(
            memory.get_all,
            filters={"user_id": str(user_id)},
            top_k=_MAX_COACHING_INSIGHTS,
        )
        return [
            MemoryInsight(
                content=m.get("memory", ""),
                category=m.get("metadata", {}).get("category", "general"),
                created_at=datetime.now(UTC),
            )
            for m in results.get("results", [])
        ]
