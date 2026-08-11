from __future__ import annotations

import json
from typing import Protocol, cast

from groq import AsyncGroq
from groq.types.chat import ChatCompletionMessageParam

from habit_tracker.infrastructure.resilience import retry_llm


class LLMClient(Protocol):
    """The slice of an LLM SDK the AI adapters actually use.

    An infrastructure-internal seam, not an application port: nothing above
    this layer knows an LLM exists. It lets the verifier and the pattern
    analyser be tested against a stub without reaching for Groq, and keeps them
    from binding to a specific SDK.
    """

    async def complete(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float | None = None,
    ) -> str: ...

    async def complete_json(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float | None = None,
    ) -> dict: ...


class GroqLLMClient:
    def __init__(self, api_key: str, model: str, temperature: float) -> None:
        self._client = AsyncGroq(api_key=api_key, max_retries=0)
        self._model = model
        self._temperature = temperature

    async def close(self) -> None:
        """Close the native Groq client's HTTP connection pool."""
        await self._client.close()

    @retry_llm()
    async def complete(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float | None = None,
    ) -> str:
        """Plain text completion."""
        selected_model = model or self._model
        selected_temperature = temperature if temperature is not None else self._temperature
        response = await self._client.chat.completions.create(
            model=selected_model,
            messages=cast(list[ChatCompletionMessageParam], messages),
            temperature=selected_temperature,
            reasoning_effort="none",
        )
        return self._content(response.choices[0].message.content)

    @retry_llm()
    async def complete_json(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float | None = None,
    ) -> dict:
        """Return a completion parsed as JSON."""
        selected_model = model or self._model
        selected_temperature = temperature if temperature is not None else self._temperature
        response = await self._client.chat.completions.create(
            model=selected_model,
            messages=cast(list[ChatCompletionMessageParam], messages),
            temperature=selected_temperature,
            reasoning_effort="none",
            response_format={"type": "json_object"},
        )
        return json.loads(self._content(response.choices[0].message.content))

    @staticmethod
    def _content(content: str | None) -> str:
        """Return response text and reject an empty assistant message."""
        if content is None:
            raise ValueError("Groq response contained no text content")
        return content
