import pytest

from habit_tracker.domain.value_objects.habit_name import HabitName
from habit_tracker.domain.value_objects.telegram_id import TelegramId


class TestTelegramId:
    def test_valid_id(self):
        tid = TelegramId(123456)
        assert tid.value == 123456

    def test_zero_raises(self):
        with pytest.raises(ValueError, match="positive"):
            TelegramId(0)

    def test_negative_raises(self):
        with pytest.raises(ValueError, match="positive"):
            TelegramId(-1)

    def test_equality(self):
        assert TelegramId(42) == TelegramId(42)

    def test_immutable(self):
        tid = TelegramId(1)
        with pytest.raises(AttributeError):
            tid.value = 2


class TestHabitName:
    def test_valid_name(self):
        name = HabitName("Read 30 min")
        assert name.value == "Read 30 min"

    def test_strips_whitespace(self):
        name = HabitName("  gym  ")
        assert name.value == "gym"

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            HabitName("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="empty"):
            HabitName("   ")

    def test_too_long_raises(self):
        with pytest.raises(ValueError, match="100"):
            HabitName("x" * 101)

    def test_max_length_ok(self):
        name = HabitName("x" * 100)
        assert len(name.value) == 100

    def test_equality(self):
        assert HabitName("gym") == HabitName("gym")
