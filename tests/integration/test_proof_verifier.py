"""Proof verification through the native Groq SDK and replayed responses."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
import json

from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.value_objects.frequency import Frequency
from habit_tracker.domain.value_objects.habit_name import HabitName
from habit_tracker.domain.value_objects.proof_result import ProofResult
from habit_tracker.domain.value_objects.verification_policy import VerificationPolicy
from habit_tracker.infrastructure.ai.llm_client import GroqLLMClient
from habit_tracker.infrastructure.ai.proof_verifier import LLMProofVerifier
from habit_tracker.infrastructure.config.settings import Settings

BLANK_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCAgICAgMCAgIDAwMDBAYEBAQEBAgGBgUGCQgKCgkICQkKDA8MCgsOCwkJDRENDg8Q"
    "EBEQCgwSExIQEw8QEBD/wAALCAACAAIBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAI"
    "AQEAAD8AVN//2Q=="
)


def _habit(
    name: str = "Morning Run",
    description: str | None = "Run 5km every morning",
    verification_policy: VerificationPolicy = VerificationPolicy.TEXT,
) -> Habit:
    return Habit(
        id=1,
        user_id=42,
        name=HabitName(name),
        description=description,
        frequency=Frequency.DAILY,
        verification_policy=verification_policy,
        is_active=True,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


def _verifier(settings: Settings) -> LLMProofVerifier:
    return LLMProofVerifier(
        GroqLLMClient(
            settings.groq_api_key,
            settings.llm_model,
            settings.llm_temperature,
        )
    )


def _sent_request(cassette) -> dict:
    request = next(request for request in cassette.requests if request.uri.endswith("/chat/completions"))
    return json.loads(request.body)


def _messages(cassette) -> list[dict]:
    return _sent_request(cassette)["messages"]


def _content_text(content: str | list[dict]) -> str:
    if isinstance(content, str):
        return content
    return " ".join(str(part.get("text", "")) for part in content)


async def test_convincing_text_proof_is_accepted(cassette, app_settings: Settings) -> None:
    result = await _verifier(app_settings).verify_text(
        _habit(),
        "I ran 5.2km along the river this morning, from 6:00 until 6:34.",
    )

    assert isinstance(result, ProofResult)
    assert result.verified is True
    assert 0.0 <= result.confidence <= 1.0
    assert result.reasoning


async def test_vague_text_proof_is_rejected(cassette, app_settings: Settings) -> None:
    result = await _verifier(app_settings).verify_text(_habit(), "did stuff")

    assert result.verified is False
    assert 0.0 <= result.confidence <= 1.0


async def test_text_prompt_and_json_format_reach_groq(cassette, app_settings: Settings) -> None:
    await _verifier(app_settings).verify_text(
        _habit(name="Meditation", description=None),
        "I meditated for 20 minutes",
    )

    messages = _messages(cassette)
    system_content = _content_text(next(message for message in messages if message["role"] == "system")["content"])
    user_content = _content_text(next(message for message in messages if message["role"] == "user")["content"])
    request = _sent_request(cassette)
    assert "Meditation" in system_content
    assert "No description provided" in system_content
    assert "I meditated for 20 minutes" in user_content
    assert request["temperature"] == 0.0
    assert request["reasoning_effort"] == "none"
    assert request["response_format"] == {"type": "json_object"}


async def test_blank_image_is_rejected_and_sent_as_data_url(cassette, app_settings: Settings) -> None:
    result = await _verifier(app_settings).verify_image(
        _habit(verification_policy=VerificationPolicy.PHOTO),
        BLANK_JPEG,
    )

    assert result.verified is False
    messages = _messages(cassette)
    system_content = _content_text(next(message for message in messages if message["role"] == "system")["content"])
    user_content = next(message for message in messages if message["role"] == "user")["content"]
    image_part = next(part for part in user_content if part["type"] == "image_url")
    image_url = image_part.get("image_url")
    if isinstance(image_url, dict):
        image_url = image_url["url"]
    assert image_url.startswith("data:image/jpeg;base64,")
    assert base64.b64encode(BLANK_JPEG).decode() in image_url
    assert "photo proof" in system_content


async def test_quiz_generation_uses_real_model(cassette, app_settings: Settings) -> None:
    question = await _verifier(app_settings).generate_quiz(_habit(name="Read Python"), "async context managers")

    assert question
    assert question != "What did you learn? Please describe the key concept in your own words."


async def test_quiz_answer_evaluation_uses_real_model(cassette, app_settings: Settings) -> None:
    result = await _verifier(app_settings).evaluate_quiz_answer(
        _habit(name="Read Python"),
        "Why is an async context manager useful?",
        "It can await setup and cleanup while guaranteeing cleanup runs when the block exits.",
    )

    assert result.verified is True
    assert 0.0 <= result.confidence <= 1.0
