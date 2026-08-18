from __future__ import annotations

from habit_tracker.domain.value_objects.habit_name import HabitName
from habit_tracker.domain.value_objects.verification_policy import VerificationPolicy

LEARNING_TERMS = (
    "learn",
    "study",
    "read",
    "course",
    "practice",
    "python",
    "programming",
    "coding",
    "language",
    "german",
    "spanish",
    "french",
)
PHOTO_TERMS = ("gym", "workout", "run", "walk", "cycle", "yoga", "swim")


def fallback_policy(habit_name: HabitName) -> VerificationPolicy:
    """Choose a deterministic policy when a provider recommendation is unavailable."""
    normalized = habit_name.value.casefold()
    if any(term in normalized for term in LEARNING_TERMS):
        return VerificationPolicy.QUIZ
    if any(term in normalized for term in PHOTO_TERMS):
        return VerificationPolicy.PHOTO
    return VerificationPolicy.TEXT
