from __future__ import annotations

import asyncio
from typing import Any

import pytest

from habit_tracker.application.services.verification_recommendation import fallback_policy
from habit_tracker.domain.value_objects.habit_name import HabitName
from habit_tracker.domain.value_objects.verification_policy import VerificationPolicy
from habit_tracker.infrastructure.ai.verification_recommender import (
    LLMVerificationRecommender,
    SafeVerificationRecommender,
)


class StubLLM:
    def __init__(self, response: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        self._response = response or {}
        self._error = error

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
    ) -> dict[str, Any]:
        if self._error:
            raise self._error
        return self._response


class HangingRecommender:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False

    async def recommend(self, habit_name: HabitName) -> VerificationPolicy:
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled = True
        raise AssertionError("unreachable")


def test_gym_falls_back_to_photo() -> None:
    assert fallback_policy(HabitName("Gym")) is VerificationPolicy.PHOTO


def test_learning_python_falls_back_to_quiz() -> None:
    assert fallback_policy(HabitName("Learn Python")) is VerificationPolicy.QUIZ


def test_unknown_habit_falls_back_to_text() -> None:
    assert fallback_policy(HabitName("Call my parents")) is VerificationPolicy.TEXT


async def test_llm_recommender_parses_supported_enum() -> None:
    llm = StubLLM({"verification_policy": "quiz"})

    result = await LLMVerificationRecommender(llm).recommend(HabitName("Learn Python"))

    assert result is VerificationPolicy.QUIZ


async def test_llm_recommender_parses_none_enum() -> None:
    result = await LLMVerificationRecommender(StubLLM({"verification_policy": "none"})).recommend(HabitName("Meditate"))

    assert result is VerificationPolicy.NONE


async def test_llm_recommender_rejects_missing_policy() -> None:
    with pytest.raises(KeyError):
        await LLMVerificationRecommender(StubLLM({})).recommend(HabitName("Gym"))


async def test_llm_recommender_rejects_unknown_policy() -> None:
    with pytest.raises(ValueError):
        await LLMVerificationRecommender(StubLLM({"verification_policy": "voice"})).recommend(HabitName("Gym"))


@pytest.mark.parametrize(
    "response",
    [
        {"verification_policy": None},
        {"verification_policy": 1},
        {"verification_policy": "quiz", "explanation": "learning habit"},
    ],
    ids=["null", "non-string", "extra-key"],
)
async def test_safe_recommender_falls_back_for_non_exact_provider_object(response: dict[str, Any]) -> None:
    delegate = LLMVerificationRecommender(StubLLM(response))

    result = await SafeVerificationRecommender(delegate).recommend(HabitName("Gym"))

    assert result is VerificationPolicy.PHOTO


async def test_safe_recommender_uses_name_fallback_on_provider_error() -> None:
    delegate = LLMVerificationRecommender(StubLLM(error=RuntimeError("offline")))

    result = await SafeVerificationRecommender(delegate).recommend(HabitName("Gym"))

    assert result is VerificationPolicy.PHOTO


async def test_safe_recommender_applies_a_short_total_deadline() -> None:
    delegate = HangingRecommender()

    async with asyncio.timeout(0.5):
        result = await SafeVerificationRecommender(
            delegate,
            timeout_seconds=0.01,
        ).recommend(HabitName("Gym"))

    assert result is VerificationPolicy.PHOTO
    assert delegate.cancelled


async def test_safe_recommender_propagates_caller_cancellation() -> None:
    delegate = HangingRecommender()
    task = asyncio.create_task(SafeVerificationRecommender(delegate, timeout_seconds=60).recommend(HabitName("Gym")))
    await delegate.started.wait()

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert delegate.cancelled
