from __future__ import annotations

from typing import Protocol

from habit_tracker.application.dtos.memory_dto import MemoryInsight
from habit_tracker.application.dtos.pattern_dto import BehavioralPattern, CheckinContext
from habit_tracker.domain.entities.completion import Completion
from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.value_objects.proof_result import ProofResult


class ProofVerifier(Protocol):
    async def verify_text(self, habit: Habit, proof_text: str) -> ProofResult: ...
    async def verify_image(self, habit: Habit, image_bytes: bytes) -> ProofResult: ...
    async def generate_quiz(self, habit: Habit, topic: str) -> str: ...
    async def evaluate_quiz_answer(self, habit: Habit, question: str, answer: str) -> ProofResult: ...


class MemoryStore(Protocol):
    async def store_insight(self, user_id: int, insight: str, category: str) -> None: ...
    async def get_insights(self, user_id: int) -> list[MemoryInsight]: ...


class PatternAnalyzer(Protocol):
    async def analyze_patterns(
        self,
        user_id: int,
        completions: dict[str, list[Completion]],
    ) -> list[BehavioralPattern]: ...
    async def generate_coaching_message(
        self, user_id: int, patterns: list[BehavioralPattern], context: CheckinContext
    ) -> str: ...
