from __future__ import annotations

from dataclasses import dataclass

from habit_tracker.domain.entities.completion import Completion
from habit_tracker.domain.entities.habit import Habit


@dataclass(frozen=True)
class BehavioralPattern:
    pattern_type: str
    description: str
    habit_name: str | None
    confidence: float


@dataclass(frozen=True)
class CheckinContext:
    habits: list[Habit]
    today_completions: list[Completion]
    patterns: list[BehavioralPattern]
