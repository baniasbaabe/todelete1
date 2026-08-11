from __future__ import annotations

from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.value_objects.completion_summary import CompletionSummary
from habit_tracker.domain.value_objects.streak import Streak
from habit_tracker.domain.value_objects.verification_policy import VerificationPolicy


def format_help() -> str:
    return (
        "Available commands:\n"
        "/start - Register and get started\n"
        "/add_habit <name> - Add a habit and choose verification\n"
        "/add_habit <name> --verify text|photo|quiz - Add immediately\n"
        "/list_habits - Show your active habits\n"
        "/delete_habit <name> - Remove a habit\n"
        "/checkin - Start daily check-in\n"
        "/help - Show this message"
    )


def format_habit_list(habits: list[Habit], streaks: list[Streak]) -> str:
    if not habits:
        return "You have no active habits. Use /add_habit to create one!"
    lines = ["Your habits:\n"]
    for habit, streak in zip(habits, streaks, strict=True):
        policy = f" [{habit.verification_policy.value}]" if habit.verification_policy != VerificationPolicy.NONE else ""
        streak_text = f" (streak: {streak.current})" if streak.current > 0 else ""
        lines.append(f"- {habit.name.value}{policy}{streak_text}")
    return "\n".join(lines)


def format_checkin_prompt(habit: Habit) -> str:
    if habit.verification_policy == VerificationPolicy.QUIZ:
        return f"Did you complete '{habit.name.value}'? Reply 'yes' to take a quick quiz, or 'skip'."
    if habit.requires_proof():
        proof_type = habit.verification_policy.value
        return f"Did you complete '{habit.name.value}'? Reply 'yes' to submit {proof_type} proof, or 'skip'."
    return f"Did you complete '{habit.name.value}'? (yes/skip)"


def format_verification_setup_complete(habit: Habit) -> str:
    """Confirm a verification choice and continue with the normal prompt."""
    return f"Verification set to {habit.verification_policy.value}.\n\n{format_checkin_prompt(habit)}"


def format_checkin_summary(summary: CompletionSummary) -> str:
    return f"Check-in complete! {summary.completed}/{summary.total} habits done.\n{summary.get_encouragement()}"
