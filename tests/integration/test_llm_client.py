"""Native Groq client against replayed real provider HTTP responses."""

from __future__ import annotations

import json

from habit_tracker.infrastructure.ai.llm_client import GroqLLMClient
from habit_tracker.infrastructure.config.settings import Settings

MESSAGES = [{"role": "user", "content": "Reply with exactly: hello from the habit bot"}]


def _provider_request(cassette) -> tuple[str, dict]:
    request = next(request for request in cassette.requests if request.uri.endswith("/chat/completions"))
    return request.uri, json.loads(request.body)


async def test_groq_plain_text_uses_chat_completions(cassette, app_settings: Settings) -> None:
    result = await GroqLLMClient(
        app_settings.groq_api_key,
        app_settings.llm_model,
        app_settings.llm_temperature,
    ).complete(MESSAGES)

    uri, body = _provider_request(cassette)
    assert result.strip() == "hello from the habit bot"
    assert uri.endswith("/chat/completions")
    assert body["model"] == "qwen/qwen3.6-27b"
    assert body["messages"] == MESSAGES
    assert body["temperature"] == 0.2
    assert body["reasoning_effort"] == "none"


async def test_groq_json_uses_json_object_mode(cassette, app_settings: Settings) -> None:
    messages = [{"role": "user", "content": 'Return JSON with one field: {"verified": true}'}]

    result = await GroqLLMClient(
        app_settings.groq_api_key,
        app_settings.llm_model,
        app_settings.llm_temperature,
    ).complete_json(messages)

    uri, body = _provider_request(cassette)
    assert result["verified"] is True
    assert uri.endswith("/chat/completions")
    assert body["response_format"] == {"type": "json_object"}
    assert body["reasoning_effort"] == "none"
