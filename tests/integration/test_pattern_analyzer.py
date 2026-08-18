"""LLM coaching through the native Groq SDK and replayed responses."""

from __future__ import annotations

from datetime import UTC, datetime
import json

from habit_tracker.application.dtos.memory_dto import MemoryInsight
from habit_tracker.application.dtos.pattern_dto import BehavioralPattern, CheckinContext
from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.value_objects.frequency import Frequency
from habit_tracker.domain.value_objects.habit_name import HabitName
from habit_tracker.domain.value_objects.verification_policy import VerificationPolicy
from habit_tracker.infrastructure.ai.llm_client import GroqLLMClient
from habit_tracker.infrastructure.ai.pattern_analyzer import LLMPatternAnalyzer
from habit_tracker.infrastructure.config.settings import Settings


class StaticMemoryStore:
    def __init__(self, insights: list[MemoryInsight] | None = None) -> None:
        self.insights = insights or []

    async def get_insights(self, user_id: int) -> list[MemoryInsight]:
        return self.insights

    async def store_insight(self, user_id: int, insight: str, category: str) -> None:
        return None


def _llm_client(settings: Settings) -> GroqLLMClient:
    return GroqLLMClient(
        settings.groq_api_key,
        settings.llm_model,
        settings.llm_temperature,
    )


def _habit(name: str) -> Habit:
    return Habit(
        id=1,
        user_id=42,
        name=HabitName(name),
        description=None,
        frequency=Frequency.DAILY,
        verification_policy=VerificationPolicy.NONE,
        is_active=True,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


def _sent_messages(cassette) -> list[dict]:
    request = next(request for request in cassette.requests if request.uri.endswith("/chat/completions"))
    body = json.loads(request.body)
    return body["messages"]


async def test_generates_a_message_with_the_real_model(cassette, app_settings: Settings) -> None:
    analyzer = LLMPatternAnalyzer(
        llm_client=_llm_client(app_settings),
        memory_store=StaticMemoryStore(),
    )
    context = CheckinContext(habits=[_habit("Morning Run")], today_completions=[], patterns=[])

    result = await analyzer.generate_coaching_message(user_id=1, patterns=[], context=context)

    assert result.strip()
    assert result != "Let's check in on your habits today!"


async def test_prompt_contains_habits_patterns_and_memory(cassette, app_settings: Settings) -> None:
    insight = MemoryInsight(
        content="User prefers morning sessions",
        category="preference",
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    analyzer = LLMPatternAnalyzer(
        llm_client=_llm_client(app_settings),
        memory_store=StaticMemoryStore([insight]),
    )
    patterns = [
        BehavioralPattern(
            pattern_type="weak_day",
            description="You rarely complete 'Run' on Sundays",
            habit_name="Run",
            confidence=0.9,
        )
    ]
    context = CheckinContext(
        habits=[_habit("Morning Run"), _habit("Meditation")],
        today_completions=[],
        patterns=[],
    )

    await analyzer.generate_coaching_message(user_id=1, patterns=patterns, context=context)

    messages = _sent_messages(cassette)
    system_message = next(message for message in messages if message["role"] == "system")["content"]
    user_message = next(message for message in messages if message["role"] == "user")["content"]
    assert "coach" in system_message.lower()
    assert "Morning Run" in user_message
    assert "Meditation" in user_message
    assert "You rarely complete 'Run' on Sundays" in user_message
    assert "User prefers morning sessions" in user_message
