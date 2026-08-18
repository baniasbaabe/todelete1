from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.value_objects import HabitName, VerificationPolicy
from habit_tracker.domain.value_objects.completion_summary import CompletionSummary
from habit_tracker.domain.value_objects.streak import Streak
from habit_tracker.presentation.formatters import (
    format_checkin_prompt,
    format_checkin_summary,
    format_habit_list,
    format_help,
)


class TestFormatters:
    def test_format_help_contains_commands(self):
        text = format_help()
        assert "/start" in text
        assert "/add_habit" in text
        assert "/checkin" in text

    def test_format_habit_list_empty(self):
        text = format_habit_list([], [])
        assert "no active habits" in text.lower()

    def test_format_habit_list_with_streak(self):
        h = Habit.create(user_id=1, name=HabitName("gym"))
        h.id = 1
        s = Streak(current=5, longest=10, is_active=True)
        text = format_habit_list([h], [s])
        assert "gym" in text
        assert "5" in text

    def test_format_checkin_prompt(self):
        h = Habit.create(user_id=1, name=HabitName("read"), verification_policy=VerificationPolicy.TEXT)
        text = format_checkin_prompt(h)
        assert "read" in text.lower()

    def test_format_summary(self):
        s = CompletionSummary(total=3, completed=2)
        text = format_checkin_summary(s)
        assert "2" in text
        assert "3" in text

    def test_format_habit_list_no_streak_when_zero(self):
        h = Habit.create(user_id=1, name=HabitName("meditate"))
        h.id = 2
        s = Streak(current=0, longest=3, is_active=False)
        text = format_habit_list([h], [s])
        assert "meditate" in text
        assert "streak" not in text

    def test_format_habit_list_shows_verification_policy(self):
        h = Habit.create(user_id=1, name=HabitName("workout"), verification_policy=VerificationPolicy.PHOTO)
        h.id = 3
        s = Streak(current=0, longest=0, is_active=False)
        text = format_habit_list([h], [s])
        assert "photo" in text.lower()

    def test_format_checkin_prompt_no_proof(self):
        h = Habit.create(user_id=1, name=HabitName("sleep"))
        text = format_checkin_prompt(h)
        assert "sleep" in text
        assert "yes/skip" in text

    def test_format_checkin_prompt_with_proof(self):
        h = Habit.create(user_id=1, name=HabitName("run"), verification_policy=VerificationPolicy.PHOTO)
        text = format_checkin_prompt(h)
        assert "run" in text
        assert "photo" in text.lower()

    def test_format_checkin_summary_encouragement(self):
        s = CompletionSummary(total=3, completed=3)
        text = format_checkin_summary(s)
        assert "3/3" in text
