from __future__ import annotations

import base64
import json
import math

import structlog

from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.value_objects.proof_result import ProofResult
from habit_tracker.infrastructure.ai.llm_client import LLMClient

logger = structlog.get_logger()

# A model that answers with something other than the requested JSON has told us
# nothing, so the completion is not credited. Failing closed is the safe default
# here: the cost of a wrongly rejected proof is one retry.
_UNPARSEABLE = ProofResult(verified=False, confidence=0.0, reasoning="Failed to parse response")

_FALLBACK_QUESTION = "What did you learn? Please describe the key concept in your own words."


def _parse_proof_result(result: object) -> ProofResult:
    """Convert a structured model response into a proof result, failing closed."""
    if not isinstance(result, dict):
        return _UNPARSEABLE

    verified = result.get("verified")
    confidence = result.get("confidence")
    reasoning = result.get("reasoning")
    if not isinstance(verified, bool):
        return _UNPARSEABLE
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return _UNPARSEABLE

    try:
        normalized_confidence = float(confidence)
    except OverflowError:
        return _UNPARSEABLE
    if not math.isfinite(normalized_confidence) or not 0.0 <= normalized_confidence <= 1.0:
        return _UNPARSEABLE
    if not isinstance(reasoning, str):
        return _UNPARSEABLE

    return ProofResult(verified=verified, confidence=normalized_confidence, reasoning=reasoning)


class LLMProofVerifier:
    def __init__(self, llm_client: LLMClient) -> None:
        self._llm = llm_client

    async def verify_text(self, habit: Habit, proof_text: str) -> ProofResult:
        return await self._verify(habit, "proof", f"My proof: {proof_text}")

    async def verify_image(self, habit: Habit, image_bytes: bytes) -> ProofResult:
        b64 = base64.b64encode(image_bytes).decode()
        return await self._verify(
            habit,
            "photo proof",
            [
                {"type": "text", "text": "Here is my photo proof:"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ],
        )

    async def generate_quiz(self, habit: Habit, topic: str) -> str:
        """Generate a single quiz question about what the user says they learned."""
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a friendly quiz master. Generate exactly one short question "
                    "to verify that a user genuinely understood what they claim to have learned.\n"
                    f"Habit: '{habit.name.value}'\n"
                    f"Description: {habit.description or 'No description provided'}\n"
                    f"Today the user says they learned about: {topic}\n\n"
                    "The question should test understanding of that specific topic, "
                    "not recall of trivia. Keep it conversational - one or two sentences. "
                    "Do NOT include the answer. Respond with JSON: "
                    '{"question": "..."}'
                ),
            },
            {"role": "user", "content": f"I learned about {topic}. Quiz me!"},
        ]
        try:
            result = await self._llm.complete_json(messages, temperature=0.7)
            question = str(result.get("question", ""))
            if question:
                return question
        except (json.JSONDecodeError, ValueError, KeyError):
            logger.exception("quiz_generation_failed", habit=habit.name.value)

        return _FALLBACK_QUESTION

    async def evaluate_quiz_answer(self, habit: Habit, question: str, answer: str) -> ProofResult:
        """Evaluate whether a quiz answer demonstrates genuine understanding."""
        messages = [
            {
                "role": "system",
                "content": (
                    f"You are evaluating a quiz answer for the habit: '{habit.name.value}'.\n"
                    f"Description: {habit.description or 'No description provided'}.\n\n"
                    f'The question was: "{question}"\n\n'
                    "Judge whether the answer shows genuine understanding of the topic. "
                    "Be encouraging but honest - a vague or completely wrong answer should "
                    "not pass. A roughly correct answer in the user's own words should pass.\n"
                    "Respond with JSON: "
                    '{"verified": true/false, "confidence": 0.0-1.0, "reasoning": "..."}'
                ),
            },
            {"role": "user", "content": f"My answer: {answer}"},
        ]

        try:
            result = await self._llm.complete_json(messages, temperature=0.0)
        except (json.JSONDecodeError, ValueError, KeyError):
            return _UNPARSEABLE

        return _parse_proof_result(result)

    async def _verify(self, habit: Habit, proof_label: str, user_content: str | list[dict]) -> ProofResult:
        """Ask the model to judge one piece of evidence.

        Text and photo verification differ only in how the evidence is carried
        in the user message; the prompt, the schema, and the failure policy are
        the same, so they live here rather than in two near-identical copies.
        """
        messages = [
            {
                "role": "system",
                "content": (
                    f"You are verifying if a user completed their habit: '{habit.name.value}'.\n"
                    f"Description: {habit.description or 'No description provided'}.\n"
                    f"Evaluate the {proof_label} and respond with JSON: "
                    '{"verified": true/false, "confidence": 0.0-1.0, "reasoning": "..."}'
                ),
            },
            {"role": "user", "content": user_content},
        ]

        try:
            result = await self._llm.complete_json(messages, temperature=0.0)
        except (json.JSONDecodeError, ValueError, KeyError):
            return _UNPARSEABLE

        return _parse_proof_result(result)
