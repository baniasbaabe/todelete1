"""Pure pattern analysis and fault handling without network calls."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from habit_tracker.application.dtos.memory_dto import MemoryInsight
from habit_tracker.application.dtos.pattern_dto import CheckinContext
from habit_tracker.domain.entities.completion import Completion
from habit_tracker.domain.value_objects.verification_policy import ProofType
from habit_tracker.infrastructure.ai.pattern_analyzer import LLMPatternAnalyzer


class StaticLLMClient:
    def __init__(self, response: str = "Keep it up!", error: Exception | None = None) -> None:
        self.response = response
        self.error = error

    async def complete(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float | None = None,
    ) -> str:
        if self.error is not None:
            raise self.error
        return self.response

    async def complete_json(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float | None = None,
    ) -> dict:
        return {}


class StaticMemoryStore:
    def __init__(self, insights: list[MemoryInsight] | None = None, error: Exception | None = None) -> None:
        self.insights = insights or []
        self.error = error
        self.requested_user_ids: list[int] = []

    async def get_insights(self, user_id: int) -> list[MemoryInsight]:
        self.requested_user_ids.append(user_id)
        if self.error is not None:
            raise self.error
        return self.insights

    async def store_insight(self, user_id: int, insight: str, category: str) -> None:
        return None


def _completion(weekday: int) -> Completion:
    completed_at = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=weekday)
    return Completion(
        id=None,
        habit_id=1,
        completed_at=completed_at,
        proof_type=ProofType.NONE,
        verified=True,
        verification_notes=None,
    )


def _analyzer(
    llm: StaticLLMClient | None = None,
    memory: StaticMemoryStore | None = None,
) -> LLMPatternAnalyzer:
    return LLMPatternAnalyzer(llm_client=llm or StaticLLMClient(), memory_store=memory or StaticMemoryStore())


async def test_empty_completion_sets_have_no_patterns() -> None:
    analyzer = _analyzer()
    assert await analyzer.analyze_patterns(1, {}) == []
    assert await analyzer.analyze_patterns(1, {"Run": []}) == []


async def test_detects_a_weak_sunday() -> None:
    completions = [_completion(week * 7 + day) for week in range(3) for day in range(6)]
    patterns = await _analyzer().analyze_patterns(1, {"Run": completions})

    assert any(pattern.habit_name == "Run" and "Sunday" in pattern.description for pattern in patterns)
    assert all(pattern.pattern_type == "weak_day" for pattern in patterns)
    assert all(0.0 <= pattern.confidence <= 1.0 for pattern in patterns)


async def test_uniform_week_has_no_weak_day() -> None:
    patterns = await _analyzer().analyze_patterns(1, {"Run": [_completion(day) for day in range(21)]})
    assert patterns == []


async def test_too_little_history_does_not_create_patterns() -> None:
    patterns = await _analyzer().analyze_patterns(1, {"Run": [_completion(0)]})

    assert patterns == []


async def test_short_observation_span_does_not_create_patterns() -> None:
    patterns = await _analyzer().analyze_patterns(1, {"Run": [_completion(day) for day in range(7)]})

    assert patterns == []


async def test_habits_are_analyzed_independently() -> None:
    patterns = await _analyzer().analyze_patterns(
        1,
        {
            "Run": [_completion(week * 7 + day) for week in range(3) for day in range(6)],
            "Meditation": [_completion(day) for day in range(21)],
        },
    )
    assert {pattern.habit_name for pattern in patterns} == {"Run"}


async def test_llm_error_returns_fallback_message() -> None:
    analyzer = _analyzer(llm=StaticLLMClient(error=RuntimeError("API down")))
    context = CheckinContext(habits=[], today_completions=[], patterns=[])

    assert await analyzer.generate_coaching_message(1, [], context) == "Let's check in on your habits today!"


async def test_memory_error_returns_fallback_message() -> None:
    analyzer = _analyzer(memory=StaticMemoryStore(error=ConnectionError("memory down")))
    context = CheckinContext(habits=[], today_completions=[], patterns=[])

    assert await analyzer.generate_coaching_message(1, [], context) == "Let's check in on your habits today!"


async def test_coaching_requests_memory_for_the_user() -> None:
    memory = StaticMemoryStore()
    analyzer = _analyzer(memory=memory)
    context = CheckinContext(habits=[], today_completions=[], patterns=[])

    await analyzer.generate_coaching_message(99, [], context)

    assert memory.requested_user_ids == [99]
