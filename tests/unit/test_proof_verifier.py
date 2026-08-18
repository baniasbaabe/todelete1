"""Proof-verifier parsing and failure behavior without an API call."""

from __future__ import annotations

from datetime import UTC, datetime
import json

import pytest

from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.value_objects.frequency import Frequency
from habit_tracker.domain.value_objects.habit_name import HabitName
from habit_tracker.domain.value_objects.verification_policy import VerificationPolicy
from habit_tracker.infrastructure.ai.proof_verifier import LLMProofVerifier


class StaticLLMClient:
    def __init__(self, response: dict | None = None, error: Exception | None = None) -> None:
        self.response = response or {}
        self.error = error

    async def complete(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float | None = None,
    ) -> str:
        return ""

    async def complete_json(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float | None = None,
    ) -> dict:
        if self.error is not None:
            raise self.error
        return self.response


def _habit() -> Habit:
    return Habit(
        id=1,
        user_id=42,
        name=HabitName("Morning Run"),
        description="Run 5km",
        frequency=Frequency.DAILY,
        verification_policy=VerificationPolicy.TEXT,
        is_active=True,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    "error",
    [json.JSONDecodeError("msg", "doc", 0), ValueError("bad value"), KeyError("choices")],
)
async def test_unparseable_text_response_fails_closed(error: Exception) -> None:
    result = await LLMProofVerifier(StaticLLMClient(error=error)).verify_text(_habit(), "proof")

    assert result.verified is False
    assert result.confidence == 0.0
    assert result.reasoning == "Failed to parse response"


async def test_empty_json_does_not_pass() -> None:
    result = await LLMProofVerifier(StaticLLMClient(response={})).verify_text(_habit(), "proof")

    assert result.verified is False
    assert result.confidence == 0.0
    assert result.reasoning == "Failed to parse response"


@pytest.mark.parametrize(
    "response",
    [
        {"verified": "false", "confidence": 0.9, "reasoning": "rejected"},
        {"verified": 1, "confidence": 0.9, "reasoning": "rejected"},
        {"verified": False, "confidence": "0.9", "reasoning": "rejected"},
        {"verified": False, "confidence": float("nan"), "reasoning": "rejected"},
        {"verified": False, "confidence": 1.1, "reasoning": "rejected"},
        {"verified": False, "confidence": 0.9, "reasoning": None},
    ],
)
async def test_malformed_json_fields_fail_closed(response: dict) -> None:
    result = await LLMProofVerifier(StaticLLMClient(response=response)).verify_text(_habit(), "proof")

    assert result.verified is False
    assert result.confidence == 0.0
    assert result.reasoning == "Failed to parse response"


async def test_valid_json_fields_are_preserved() -> None:
    response = {"verified": False, "confidence": 0.9, "reasoning": "Not enough detail"}

    result = await LLMProofVerifier(StaticLLMClient(response=response)).verify_text(_habit(), "proof")

    assert result.verified is False
    assert result.confidence == 0.9
    assert result.reasoning == "Not enough detail"


async def test_unrepresentably_large_confidence_fails_closed() -> None:
    response = {"verified": True, "confidence": 10**10000, "reasoning": "Impossible confidence"}

    result = await LLMProofVerifier(StaticLLMClient(response=response)).verify_text(_habit(), "proof")

    assert result.verified is False
    assert result.confidence == 0.0
    assert result.reasoning == "Failed to parse response"


async def test_unparseable_image_response_fails_closed() -> None:
    result = await LLMProofVerifier(StaticLLMClient(error=ValueError("bad"))).verify_image(_habit(), b"jpeg")

    assert result.verified is False
    assert result.reasoning == "Failed to parse response"


async def test_quiz_generation_error_returns_fallback() -> None:
    question = await LLMProofVerifier(StaticLLMClient(error=ValueError("bad"))).generate_quiz(
        _habit(),
        "asyncio",
    )

    assert question == "What did you learn? Please describe the key concept in your own words."
