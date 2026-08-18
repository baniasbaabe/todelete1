from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime

from habit_tracker.application.dtos.memory_dto import MemoryInsight
from habit_tracker.domain.entities.completion import Completion
from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.entities.user import User
from habit_tracker.domain.exceptions import (
    CompletionNotFoundError,
    HabitAlreadyExistsError,
    HabitNotFoundError,
    UserNotFoundError,
)
from habit_tracker.domain.value_objects import HabitName, TelegramId
from habit_tracker.domain.value_objects.proof_result import ProofResult
from habit_tracker.domain.value_objects.verification_policy import VerificationPolicy


class InMemoryUserRepository:
    def __init__(self) -> None:
        self._users: dict[int, User] = {}
        self._next_id = 1

    async def save(self, user: User) -> User:
        if user.id is None:
            user = dataclasses.replace(user, id=self._next_id)
            self._next_id += 1
        elif user.id not in self._users:
            raise UserNotFoundError(f"User {user.id} no longer exists")
        self._users[user.id] = user
        return user

    async def find_by_telegram_id(self, telegram_id: TelegramId) -> User | None:
        return next((u for u in self._users.values() if u.telegram_id == telegram_id), None)


class InMemoryHabitRepository:
    def __init__(self) -> None:
        self._habits: dict[int, Habit] = {}
        self._next_id = 1

    async def save(self, habit: Habit) -> Habit:
        if habit.id is None:
            # Mirrors the partial unique index on (user_id, name) WHERE
            # is_active. The fakes drifting from the real schema is what let
            # the missing is_active filter go unnoticed; don't repeat it.
            if habit.is_active and await self.find_active_by_user_and_name(habit.user_id, habit.name):
                raise HabitAlreadyExistsError(f"Habit '{habit.name.value}' already exists")
            habit.id = self._next_id
            self._next_id += 1
        elif habit.id not in self._habits:
            raise HabitNotFoundError(f"Habit {habit.id} no longer exists")
        self._habits[habit.id] = habit
        return habit

    async def find_by_id(self, habit_id: int) -> Habit | None:
        return self._habits.get(habit_id)

    async def find_active_by_user(self, user_id: int) -> list[Habit]:
        return [h for h in self._habits.values() if h.user_id == user_id and h.is_active]

    async def find_active_by_user_and_name(self, user_id: int, name: HabitName) -> Habit | None:
        return next(
            (h for h in self._habits.values() if h.user_id == user_id and h.name == name and h.is_active),
            None,
        )

    async def delete(self, habit_id: int) -> None:
        self._habits.pop(habit_id, None)


class InMemoryCompletionRepository:
    def __init__(self) -> None:
        self._completions: dict[int, Completion] = {}
        self._next_id = 1

    async def save(self, completion: Completion) -> Completion:
        if completion.id is None:
            completion = dataclasses.replace(completion, id=self._next_id)
            self._next_id += 1
        elif completion.id not in self._completions:
            raise CompletionNotFoundError(f"Completion {completion.id} no longer exists")
        self._completions[completion.id] = completion
        return completion

    async def find_today_by_habits(self, habit_ids: list[int]) -> list[Completion]:
        # UTC, matching the real repository. A local date.today() here would
        # hide off-by-a-day bugs the same way the missing is_active filter did.
        today = datetime.now(UTC).date()
        return [c for c in self._completions.values() if c.habit_id in habit_ids and c.completed_at.date() == today]

    async def get_completion_dates(self, habit_id: int) -> list[date]:
        return sorted(
            {c.completed_at.date() for c in self._completions.values() if c.habit_id == habit_id},
            reverse=True,
        )

    async def get_completion_dates_by_habits(self, habit_ids: list[int]) -> dict[int, list[date]]:
        return {habit_id: await self.get_completion_dates(habit_id) for habit_id in habit_ids}

    async def find_by_habits_since(self, habit_ids: list[int], since: date) -> dict[int, list[Completion]]:
        grouped: dict[int, list[Completion]] = {habit_id: [] for habit_id in habit_ids}
        for c in self._completions.values():
            if c.habit_id in grouped and c.completed_at.date() >= since:
                grouped[c.habit_id].append(c)
        return grouped


class FakeProofVerifier:
    def __init__(self, result_verified: bool = True, quiz_question: str = "What is 2+2?") -> None:
        self._result_verified = result_verified
        self._quiz_question = quiz_question

    async def verify_text(self, habit, proof_text):
        return ProofResult(verified=self._result_verified, confidence=0.9, reasoning="test")

    async def verify_image(self, habit, image_bytes):
        return ProofResult(verified=self._result_verified, confidence=0.85, reasoning="test image")

    async def generate_quiz(self, habit, topic):
        return self._quiz_question

    async def evaluate_quiz_answer(self, habit, question, answer):
        return ProofResult(verified=self._result_verified, confidence=0.9, reasoning="test quiz")


class FakeVerificationRecommender:
    def __init__(self, policy: VerificationPolicy = VerificationPolicy.TEXT) -> None:
        self.policy = policy
        self.names: list[str] = []

    async def recommend(self, habit_name: HabitName) -> VerificationPolicy:
        self.names.append(habit_name.value)
        return self.policy


class FakePatternAnalyzer:
    async def analyze_patterns(self, user_id, completions):
        return []

    async def generate_coaching_message(self, user_id, patterns, context):
        return "Keep going!"


class FakeMemoryStore:
    """In-memory MemoryStore that actually round-trips, so a broken write is visible."""

    def __init__(self) -> None:
        self.stored: list[dict] = []

    async def store_insight(self, user_id: int, insight: str, category: str) -> None:
        self.stored.append({"user_id": user_id, "insight": insight, "category": category})

    async def get_insights(self, user_id: int) -> list[MemoryInsight]:
        return [
            MemoryInsight(content=s["insight"], category=s["category"], created_at=datetime.now(UTC))
            for s in self.stored
            if s["user_id"] == user_id
        ]
