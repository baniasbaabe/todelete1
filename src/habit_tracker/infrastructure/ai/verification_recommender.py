from __future__ import annotations

import structlog

from habit_tracker.application.ports.ai_services import VerificationRecommender
from habit_tracker.application.services.verification_recommendation import fallback_policy
from habit_tracker.domain.value_objects.habit_name import HabitName
from habit_tracker.domain.value_objects.verification_policy import VerificationPolicy
from habit_tracker.infrastructure.ai.llm_client import LLMClient

logger = structlog.get_logger()


class LLMVerificationRecommender:
    """Recommend a verification policy with a structured LLM completion."""

    def __init__(self, llm_client: LLMClient) -> None:
        self._llm = llm_client

    async def recommend(self, habit_name: HabitName) -> VerificationPolicy:
        result = await self._llm.complete_json(
            [
                {
                    "role": "system",
                    "content": (
                        "Recommend habit verification. Return JSON with exactly one key, "
                        "verification_policy, valued photo, quiz, text, or none. Use photo "
                        "for visible activity, quiz for learning, text for written evidence, "
                        "and none only when verification is impractical."
                    ),
                },
                {"role": "user", "content": f"Habit: {habit_name.value}"},
            ],
            temperature=0.0,
        )
        return VerificationPolicy(str(result["verification_policy"]).casefold())


class SafeVerificationRecommender:
    """Return a deterministic recommendation when the provider cannot respond."""

    def __init__(self, delegate: VerificationRecommender) -> None:
        self._delegate = delegate

    async def recommend(self, habit_name: HabitName) -> VerificationPolicy:
        try:
            return await self._delegate.recommend(habit_name)
        except Exception:
            logger.exception("verification_recommendation_failed")
            return fallback_policy(habit_name)
