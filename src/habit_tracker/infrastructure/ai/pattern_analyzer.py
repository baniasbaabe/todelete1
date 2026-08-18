"""LLM-backed implementation of the PatternAnalyzer protocol."""

from __future__ import annotations

import structlog

from habit_tracker.application.dtos.pattern_dto import BehavioralPattern, CheckinContext
from habit_tracker.application.ports.ai_services import MemoryStore
from habit_tracker.domain.entities.completion import Completion
from habit_tracker.infrastructure.ai.llm_client import LLMClient

logger = structlog.get_logger()

_DAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]
_MIN_PATTERN_COMPLETIONS = 7
_MIN_PATTERN_SPAN_DAYS = 14


class LLMPatternAnalyzer:
    """Detects behavioural patterns in habit completions and generates coaching messages.

    ``analyze_patterns`` is pure Python — no LLM call — making it fast and
    easily testable in isolation.

    ``generate_coaching_message`` makes a single LLM call, enriched with
    personal insights fetched from the MemoryStore.
    """

    def __init__(self, llm_client: LLMClient, memory_store: MemoryStore) -> None:
        self._llm = llm_client
        self._memory = memory_store

    async def analyze_patterns(
        self,
        user_id: int,
        completions: dict[str, list[Completion]],
    ) -> list[BehavioralPattern]:
        """Return behavioural patterns detected from historical completion data.

        For each habit the algorithm:
        1. Counts completions per weekday (0 = Monday, 6 = Sunday).
        2. Flags any weekday whose count is below 30 % of the per-day average
           (i.e., the habit is rarely done on that day) as a ``weak_day``
           pattern.

        Args:
            user_id: Telegram user ID (kept for future personalisation).
            completions: Mapping of daily habit names to Completion objects.
                         Each Completion must expose a ``completed_at``
                         datetime attribute.

        Returns
        -------
            A (possibly empty) list of BehavioralPattern instances.
        """
        patterns: list[BehavioralPattern] = []

        for habit_name, comps in completions.items():
            if len(comps) < _MIN_PATTERN_COMPLETIONS:
                continue

            completion_dates = [completion.completed_at.date() for completion in comps]
            observation_span = (max(completion_dates) - min(completion_dates)).days + 1
            if observation_span < _MIN_PATTERN_SPAN_DAYS:
                continue

            # Tally completions by weekday (0=Mon … 6=Sun)
            day_counts = [0] * 7
            for c in comps:
                day_counts[c.completed_at.weekday()] += 1

            total = sum(day_counts)
            if total == 0:
                continue

            avg = total / 7  # expected completions per day if perfectly uniform

            for day_idx, count in enumerate(day_counts):
                if avg > 0 and count / avg < 0.3:
                    day_name = _DAY_NAMES[day_idx]
                    # Confidence rises as the observed count drops further below avg
                    confidence = 0.7 + 0.3 * (1 - count / avg) if avg > 0 else 0.7
                    confidence = min(confidence, 1.0)
                    patterns.append(
                        BehavioralPattern(
                            pattern_type="weak_day",
                            description=f"You rarely complete '{habit_name}' on {day_name}s",
                            habit_name=habit_name,
                            confidence=confidence,
                        )
                    )

        return patterns

    async def generate_coaching_message(
        self,
        user_id: int,
        patterns: list[BehavioralPattern],
        context: CheckinContext,
    ) -> str:
        """Generate a short, personalised coaching message via a single LLM call.

        Falls back to a generic message if anything goes wrong so the bot
        is never silenced by an LLM or memory failure.
        """
        try:
            insights = await self._memory.get_insights(user_id)

            pattern_text = "\n".join(f"- {p.description}" for p in patterns) or "No patterns detected yet."
            insight_text = "\n".join(f"- {i.content}" for i in insights) or "No prior insights."
            habit_text = "\n".join(f"- {h.name.value}" for h in context.habits)

            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a supportive habit coach. "
                        "Generate a short, personal check-in message (2-3 sentences). "
                        "Be encouraging but specific."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"User's patterns:\n{pattern_text}\n\n"
                        f"Prior insights:\n{insight_text}\n\n"
                        f"Today's pending habits:\n{habit_text}"
                    ),
                },
            ]

            return await self._llm.complete(messages)

        except Exception:
            logger.exception("pattern_analyzer_coaching_error", user_id=user_id)
            return "Let's check in on your habits today!"
