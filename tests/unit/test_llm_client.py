from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from habit_tracker.infrastructure.ai.llm_client import GroqLLMClient
from habit_tracker.infrastructure.config.settings import Settings


def test_client_stores_defaults() -> None:
    settings = Settings(
        telegram_bot_token="telegram-test",
        database_url="postgresql+asyncpg://u:p@host:5432/db",
        groq_api_key="groq-test",
        jina_api_key="jina-test",
        llm_model="qwen/qwen3.6-27b",
        llm_temperature=0.2,
        jina_embedding_model="jina-embeddings-v5-text-small",
        mem0_embedding_dims=1024,
        mem0_collection_name="memories",
        mem0_telemetry=False,
        collector_endpoint=None,
        enable_tracing=False,
        webhook_url=None,
        webhook_secret=None,
        phoenix_api_key=None,
    )
    client = GroqLLMClient(settings.groq_api_key, settings.llm_model, settings.llm_temperature)

    assert client._model == "qwen/qwen3.6-27b"
    assert client._temperature == 0.2
    assert client._client.max_retries == 0


async def test_client_disables_reasoning_for_every_completion(monkeypatch) -> None:
    requests: list[dict] = []

    async def fake_completion(**kwargs) -> SimpleNamespace:
        requests.append(kwargs)
        content = '{"verified": true}' if "response_format" in kwargs else "hello"
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    client = GroqLLMClient("test-key", "qwen/qwen3.6-27b", 0.2)
    monkeypatch.setattr(client._client.chat.completions, "create", fake_completion)

    assert await client.complete([{"role": "user", "content": "hello"}]) == "hello"
    assert await client.complete_json([{"role": "user", "content": "verify"}]) == {"verified": True}
    assert all(request["model"] == "qwen/qwen3.6-27b" for request in requests)
    assert all(request["reasoning_effort"] == "none" for request in requests)


async def test_client_rejects_response_without_text(monkeypatch) -> None:
    async def fake_completion(**kwargs) -> SimpleNamespace:
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None))])

    client = GroqLLMClient("test-key", "qwen/qwen3.6-27b", 0.2)
    monkeypatch.setattr(client._client.chat.completions, "create", fake_completion)

    with pytest.raises(ValueError, match="no text content"):
        await client.complete([{"role": "user", "content": "hello"}])


async def test_client_closes_native_http_pool(monkeypatch) -> None:
    client = GroqLLMClient("test-key", "qwen/qwen3.6-27b", 0.2)
    close = AsyncMock()
    monkeypatch.setattr(client._client, "close", close)

    await client.close()

    close.assert_awaited_once()
