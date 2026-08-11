"""Mem0 adapter behavior with deterministic in-process collaborators."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from mem0.memory import main as mem0_main, telemetry as mem0_telemetry
from mem0.utils.factory import LlmFactory
import pytest

from habit_tracker.application.dtos.memory_dto import MemoryInsight
from habit_tracker.infrastructure.memory.mem0_store import _COMPACT_EXTRACTION_PROMPT, Mem0MemoryStore


class FakeMemory:
    def __init__(self, results: list[dict[str, Any]] | None = None) -> None:
        self.results = results or []
        self.added: list[tuple[str, str, dict[str, str]]] = []
        self.add_error: Exception | None = None
        self.get_error: Exception | None = None
        self.requested_filters: list[dict[str, str]] = []
        self.requested_top_k: list[int] = []
        self.infer_values: list[bool] = []

    def add(self, insight: str, *, user_id: str, metadata: dict[str, str], infer: bool = True) -> None:
        if self.add_error is not None:
            raise self.add_error
        self.infer_values.append(infer)
        self.added.append((insight, user_id, metadata))

    def get_all(self, *, filters: dict[str, str], top_k: int = 20) -> dict[str, list[dict[str, Any]]]:
        if self.get_error is not None:
            raise self.get_error
        self.requested_filters.append(filters)
        self.requested_top_k.append(top_k)
        return {"results": self.results}


class MemoryFactory:
    def __init__(self, *results: FakeMemory | Exception) -> None:
        self.results = list(results)
        self.calls = 0

    def from_config(self, config: dict) -> FakeMemory:
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _store(factory: MemoryFactory) -> Mem0MemoryStore:
    store = Mem0MemoryStore(config={})
    store._memory_cls = factory
    return store


@pytest.fixture(autouse=True)
def run_thread_work_inline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep these adapter unit tests deterministic; real threads run in integration."""

    async def run_inline(function: Callable, *args: Any, **kwargs: Any) -> Any:
        return function(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", run_inline)


def test_construction_is_lazy() -> None:
    factory = MemoryFactory(FakeMemory())
    store = _store(factory)

    assert store._memory is None
    assert factory.calls == 0


def test_mem0_uses_compact_extraction_prompt() -> None:
    _store(MemoryFactory(FakeMemory()))

    assert mem0_main.ADDITIVE_EXTRACTION_PROMPT == _COMPACT_EXTRACTION_PROMPT
    assert len(_COMPACT_EXTRACTION_PROMPT.split()) < 150


def test_mem0_groq_json_requests_disable_reasoning(monkeypatch: pytest.MonkeyPatch) -> None:
    _store(MemoryFactory(FakeMemory()))
    llm = LlmFactory.create(
        "groq",
        {
            "api_key": "test-key",
            "model": "qwen/qwen3.6-27b",
            "temperature": 0.2,
            "max_tokens": 512,
        },
    )
    requests: list[dict] = []

    def fake_completion(**kwargs: Any) -> SimpleNamespace:
        requests.append(kwargs)
        message = SimpleNamespace(content='{"memory": []}', tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(llm.client.chat.completions, "create", fake_completion)

    result = llm.generate_response(
        messages=[{"role": "user", "content": "Store this check-in."}],
        response_format={"type": "json_object"},
    )

    assert result == '{"memory": []}'
    assert requests[0]["reasoning_effort"] == "none"


def test_mem0_telemetry_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mem0_telemetry, "MEM0_TELEMETRY", True)
    monkeypatch.setattr(mem0_main, "MEM0_TELEMETRY", True)
    telemetry_client = MagicMock()
    oss_telemetry_client = MagicMock()
    monkeypatch.setattr(mem0_telemetry, "client_telemetry", telemetry_client)
    monkeypatch.setattr(mem0_telemetry, "_oss_telemetry_instance", oss_telemetry_client)

    _store(MemoryFactory(FakeMemory()))

    assert mem0_telemetry.MEM0_TELEMETRY is False
    assert mem0_main.MEM0_TELEMETRY is False
    telemetry_client.close.assert_called_once_with()
    oss_telemetry_client.close.assert_called_once_with()
    assert mem0_telemetry._oss_telemetry_instance is None


async def test_first_use_connects_once_and_reuses_client() -> None:
    memory = FakeMemory()
    factory = MemoryFactory(memory)
    store = _store(factory)

    await store.store_insight(1, "a", "x")
    await store.get_insights(1)

    assert factory.calls == 1


async def test_transient_connection_failure_is_retried() -> None:
    memory = FakeMemory()
    factory = MemoryFactory(ConnectionError("down"), memory)
    store = _store(factory)

    await store.store_insight(1, "kept", "habit")

    assert factory.calls == 2
    assert memory.added == [("kept", "1", {"category": "habit"})]


async def test_outage_is_swallowed_and_a_later_call_recovers() -> None:
    memory = FakeMemory()
    factory = MemoryFactory(ConnectionError("down"), ConnectionError("still down"), memory)
    store = _store(factory)

    await store.store_insight(1, "lost", "habit")
    await store.store_insight(1, "kept", "habit")

    assert memory.added == [("kept", "1", {"category": "habit"})]


async def test_store_maps_arguments_and_swallows_mem0_error() -> None:
    memory = FakeMemory()
    store = _store(MemoryFactory(memory))
    await store.store_insight(42, "Slept 8 hours", "sleep")
    assert memory.added == [("Slept 8 hours", "42", {"category": "sleep"})]
    assert memory.infer_values == [True]

    memory.add_error = RuntimeError("connection refused")
    assert await store.store_insight(42, "ignored", "sleep") is None


async def test_get_maps_results_and_defaults() -> None:
    memory = FakeMemory([
        {"memory": "Loves morning runs", "metadata": {"category": "exercise"}},
        {"memory": "Bare entry"},
        {"metadata": {"category": "unknown"}},
    ])
    store = _store(MemoryFactory(memory))

    insights = await store.get_insights(77)

    assert all(isinstance(insight, MemoryInsight) for insight in insights)
    assert [(insight.content, insight.category) for insight in insights] == [
        ("Loves morning runs", "exercise"),
        ("Bare entry", "general"),
        ("", "unknown"),
    ]
    assert all(insight.created_at.tzinfo is not None for insight in insights)
    assert memory.requested_filters == [{"user_id": "77"}]
    assert memory.requested_top_k == [20]


async def test_get_returns_empty_on_mem0_error() -> None:
    memory = FakeMemory()
    memory.get_error = ConnectionError("down")
    store = _store(MemoryFactory(memory))

    assert await store.get_insights(1) == []
