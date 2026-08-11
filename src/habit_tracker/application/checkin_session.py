from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.value_objects.completion_summary import CompletionSummary
from habit_tracker.domain.value_objects.frequency import Frequency
from habit_tracker.domain.value_objects.habit_name import HabitName
from habit_tracker.domain.value_objects.verification_policy import (
    VerificationPolicy,
)

TTL_HOURS = 24


class SessionState(StrEnum):
    AWAITING_RESPONSE = "awaiting_response"
    AWAITING_VERIFICATION_SETUP = "awaiting_verification_setup"
    AWAITING_PROOF = "awaiting_proof"
    AWAITING_QUIZ_TOPIC = "awaiting_quiz_topic"
    AWAITING_QUIZ_ANSWER = "awaiting_quiz_answer"
    DONE = "done"


@dataclass
class CheckinResult:
    habit_name: str
    completed: bool
    skipped: bool


@dataclass
class CheckinSession:
    user_id: int
    habits: list[Habit]
    current_index: int = 0
    results: list[CheckinResult] = field(default_factory=list)
    state: SessionState = SessionState.AWAITING_RESPONSE
    quiz_question: str | None = None
    verification_recommendation: VerificationPolicy | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def start(cls, user_id: int, habits: list[Habit]) -> CheckinSession:
        return cls(user_id=user_id, habits=habits)

    def current_habit(self) -> Habit | None:
        if self.current_index < len(self.habits):
            return self.habits[self.current_index]
        return None

    def advance(self) -> Habit | None:
        self.current_index += 1
        self.verification_recommendation = None
        if self.current_index >= len(self.habits):
            self.state = SessionState.DONE
            return None
        self.state = SessionState.AWAITING_RESPONSE
        return self.habits[self.current_index]

    def record_skip(self) -> None:
        habit = self.current_habit()
        if habit:
            self.results.append(CheckinResult(habit_name=habit.name.value, completed=False, skipped=True))

    def record_completion(self) -> None:
        habit = self.current_habit()
        if habit:
            self.results.append(CheckinResult(habit_name=habit.name.value, completed=True, skipped=False))

    def is_complete(self) -> bool:
        return self.state == SessionState.DONE

    def is_expired(self) -> bool:
        return datetime.now(UTC) - self.created_at > timedelta(hours=TTL_HOURS)

    def get_summary(self) -> CompletionSummary:
        total = len(self.results)
        completed = sum(1 for r in self.results if r.completed)
        return CompletionSummary(total=total, completed=completed)

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "current_index": self.current_index,
            "state": self.state.value,
            "quiz_question": self.quiz_question,
            "verification_recommendation": (
                self.verification_recommendation.value if self.verification_recommendation is not None else None
            ),
            "created_at": self.created_at.isoformat(),
            "habits": [
                {
                    "id": h.id,
                    "user_id": h.user_id,
                    "name": h.name.value,
                    "description": h.description,
                    "frequency": h.frequency.value,
                    "verification_policy": h.verification_policy.value,
                    "is_active": h.is_active,
                    "created_at": h.created_at.isoformat(),
                }
                for h in self.habits
            ],
            "results": [
                {"habit_name": r.habit_name, "completed": r.completed, "skipped": r.skipped} for r in self.results
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> CheckinSession:
        habits = [
            Habit(
                id=h["id"],
                user_id=h["user_id"],
                name=HabitName(h["name"]),
                description=h["description"],
                frequency=Frequency(h["frequency"]),
                verification_policy=VerificationPolicy(h["verification_policy"]),
                is_active=h["is_active"],
                created_at=datetime.fromisoformat(h["created_at"]),
            )
            for h in data["habits"]
        ]
        results = [
            CheckinResult(
                habit_name=r["habit_name"],
                completed=r["completed"],
                skipped=r["skipped"],
            )
            for r in data["results"]
        ]
        return cls(
            user_id=data["user_id"],
            habits=habits,
            current_index=data["current_index"],
            results=results,
            state=SessionState(data["state"]),
            quiz_question=data.get("quiz_question"),
            verification_recommendation=(
                VerificationPolicy(data["verification_recommendation"])
                if data.get("verification_recommendation") is not None
                else None
            ),
            created_at=datetime.fromisoformat(data["created_at"]),
        )
