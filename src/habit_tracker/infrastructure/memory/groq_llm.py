"""Mem0 Groq adapter with reasoning disabled for extraction requests."""

from __future__ import annotations

import logging
from typing import Any

from mem0.llms.groq import GroqLLM

logger = logging.getLogger(__name__)


class ReasoningDisabledGroqLLM(GroqLLM):
    """Preserve Mem0's Groq behavior while disabling Qwen reasoning tokens."""

    def generate_response(
        self,
        messages: list[dict[str, str]],
        response_format: Any | None = None,
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
    ) -> Any:
        """Generate a Groq response without spending output tokens on reasoning."""
        params: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "top_p": self.config.top_p,
            "reasoning_effort": "none",
        }
        if response_format:
            requests_json = isinstance(response_format, dict) and response_format.get("type") in (
                "json_object",
                "json_schema",
            )
            if requests_json and not self._supports_json_mode(self.config.model):
                logger.debug(
                    "Model '%s' does not support JSON response_format; sending the request without it.",
                    self.config.model,
                )
            else:
                params["response_format"] = response_format
        if tools:
            params["tools"] = tools
            params["tool_choice"] = tool_choice

        response = self.client.chat.completions.create(**params)
        return self._parse_response(response, tools)
