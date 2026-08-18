"""Verification recommendations through the native Groq SDK and VCR."""

from __future__ import annotations

import json

from habit_tracker.domain.value_objects.habit_name import HabitName
from habit_tracker.domain.value_objects.verification_policy import VerificationPolicy
from habit_tracker.infrastructure.ai.llm_client import GroqLLMClient
from habit_tracker.infrastructure.ai.verification_recommender import LLMVerificationRecommender
from habit_tracker.infrastructure.config.settings import Settings


async def test_gym_recommends_photo(cassette, app_settings: Settings) -> None:
    llm = GroqLLMClient(app_settings.groq_api_key, app_settings.llm_model, app_settings.llm_temperature)
    try:
        result = await LLMVerificationRecommender(llm).recommend(HabitName("Gym workout"))
    finally:
        await llm.close()

    request = next(request for request in cassette.requests if request.uri.endswith("/chat/completions"))
    body = json.loads(request.body)
    assert result is VerificationPolicy.PHOTO
    assert body["reasoning_effort"] == "none"
    assert body["response_format"] == {"type": "json_object"}


async def test_learning_python_recommends_quiz(cassette, app_settings: Settings) -> None:
    llm = GroqLLMClient(app_settings.groq_api_key, app_settings.llm_model, app_settings.llm_temperature)
    try:
        result = await LLMVerificationRecommender(llm).recommend(HabitName("Learn Python"))
    finally:
        await llm.close()

    assert result is VerificationPolicy.QUIZ
