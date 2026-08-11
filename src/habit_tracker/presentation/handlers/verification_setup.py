"""JSON-safe temporary state for guided verification setup."""

from __future__ import annotations

from dataclasses import dataclass

from habit_tracker.domain.value_objects import HabitName, VerificationPolicy

PENDING_HABIT_KEY = "pending_habit_setup"
CONFIGURED_NONE_KEY = "configured_none_habit_ids"


@dataclass(frozen=True)
class PendingHabitSetup:
    """The habit awaiting confirmation of its recommended verification policy."""

    name: HabitName
    recommendation: VerificationPolicy


def save_pending_setup(user_data: dict, setup: PendingHabitSetup) -> None:
    """Store a pending setup using only JSON-safe primitives."""
    user_data[PENDING_HABIT_KEY] = {
        "name": setup.name.value,
        "recommendation": setup.recommendation.value,
    }


def load_pending_setup(user_data: dict) -> PendingHabitSetup | None:
    """Load pending setup state, removing invalid persisted data."""
    data = user_data.get(PENDING_HABIT_KEY)
    if not isinstance(data, dict):
        user_data.pop(PENDING_HABIT_KEY, None)
        return None

    try:
        name = data["name"]
        recommendation = data["recommendation"]
        if isinstance(name, str) and isinstance(recommendation, str):
            return PendingHabitSetup(HabitName(name), VerificationPolicy(recommendation))
    except (KeyError, TypeError, ValueError):
        pass

    user_data.pop(PENDING_HABIT_KEY, None)
    return None


def clear_pending_setup(user_data: dict) -> None:
    """Remove pending setup state."""
    user_data.pop(PENDING_HABIT_KEY, None)


def parse_setup_choice(choice: str, recommendation: VerificationPolicy) -> VerificationPolicy | None:
    """Return the selected policy, or ``None`` for an unrecognised choice."""
    normalized = choice.strip().lower()
    if normalized == "yes":
        return recommendation
    try:
        return VerificationPolicy(normalized)
    except ValueError:
        return None


def is_setup_cancel(choice: str) -> bool:
    """Return whether the user cancelled guided verification setup."""
    return choice.strip().lower() == "cancel"


def mark_none_configured(user_data: dict, habit_id: int) -> None:
    """Record that a habit's explicit no-verification choice was configured."""
    if not isinstance(habit_id, int) or isinstance(habit_id, bool):
        raise TypeError("habit_id must be an integer")

    habit_ids = _configured_none_ids(user_data)
    if habit_id not in habit_ids:
        habit_ids.append(habit_id)
    user_data[CONFIGURED_NONE_KEY] = habit_ids


def is_none_configured(user_data: dict, habit_id: int) -> bool:
    """Return whether the habit has an explicit no-verification configuration."""
    return habit_id in _configured_none_ids(user_data)


def format_setup_prompt(name: HabitName, recommendation: VerificationPolicy) -> str:
    """Format the guided verification setup prompt."""
    return (
        f'For "{name.value}", I recommend {recommendation.value} verification.\n'
        "Reply 'yes' to use it, or choose: photo, quiz, text, none.\n"
        "Reply 'cancel' to stop."
    )


def _configured_none_ids(user_data: dict) -> list[int]:
    """Return valid persisted habit IDs as JSON-safe integers."""
    stored_ids = user_data.get(CONFIGURED_NONE_KEY, [])
    if not isinstance(stored_ids, list):
        return []
    return [habit_id for habit_id in stored_ids if isinstance(habit_id, int) and not isinstance(habit_id, bool)]
