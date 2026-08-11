from datetime import UTC, date, datetime, timedelta

from habit_tracker.domain.value_objects.frequency import Frequency
from habit_tracker.domain.value_objects.streak import Streak


class TestDailyStreak:
    def test_no_dates(self):
        streak = Streak.from_dates([], Frequency.DAILY)
        assert streak.current == 0
        assert streak.longest == 0
        assert streak.is_active is False

    def test_single_date_today(self):
        streak = Streak.from_dates([date.today()], Frequency.DAILY)
        assert streak.current == 1
        assert streak.longest == 1
        assert streak.is_active is True

    def test_single_date_yesterday(self):
        streak = Streak.from_dates([date.today() - timedelta(days=1)], Frequency.DAILY)
        assert streak.current == 1
        assert streak.longest == 1
        assert streak.is_active is True

    def test_single_date_two_days_ago(self):
        streak = Streak.from_dates([date.today() - timedelta(days=2)], Frequency.DAILY)
        assert streak.current == 0
        assert streak.longest == 1
        assert streak.is_active is False

    def test_consecutive_days(self):
        today = date.today()
        dates = [today - timedelta(days=i) for i in range(5)]
        streak = Streak.from_dates(dates, Frequency.DAILY)
        assert streak.current == 5
        assert streak.longest == 5
        assert streak.is_active is True

    def test_gap_breaks_current_but_not_longest(self):
        today = date.today()
        dates = [today, today - timedelta(days=1)]
        old = [today - timedelta(days=10 + i) for i in range(7)]
        streak = Streak.from_dates(dates + old, Frequency.DAILY)
        assert streak.current == 2
        assert streak.longest == 7

    def test_duplicate_dates_ignored(self):
        today = date.today()
        dates = [today, today, today - timedelta(days=1), today - timedelta(days=1)]
        streak = Streak.from_dates(dates, Frequency.DAILY)
        assert streak.current == 2

    def test_unordered_input(self):
        today = date.today()
        dates = [today - timedelta(days=2), today, today - timedelta(days=1)]
        streak = Streak.from_dates(dates, Frequency.DAILY)
        assert streak.current == 3


class TestWeeklyStreak:
    def test_no_dates(self):
        streak = Streak.from_dates([], Frequency.WEEKLY)
        assert streak.current == 0
        assert streak.is_active is False

    def test_completion_this_week(self):
        streak = Streak.from_dates([date.today()], Frequency.WEEKLY)
        assert streak.current == 1
        assert streak.is_active is True

    def test_consecutive_weeks(self):
        today = date.today()
        dates = [today - timedelta(weeks=i) for i in range(4)]
        streak = Streak.from_dates(dates, Frequency.WEEKLY)
        assert streak.current == 4
        assert streak.longest == 4


class TestStreakReferenceDate:
    """`today` defaults to UTC and is injectable.

    Completion dates come out of the database in UTC. Deriving "today" from the
    process's local clock instead put the two on different days for users far
    enough from Greenwich, flipping a streak inactive a day early or keeping it
    alive a day too long.
    """

    def test_today_can_be_pinned(self):
        anchor = date(2026, 3, 14)
        dates = [anchor - timedelta(days=i) for i in range(3)]

        streak = Streak.from_dates(dates, Frequency.DAILY, today=anchor)

        assert streak.current == 3
        assert streak.is_active is True

    def test_streak_is_inactive_two_days_after_the_last_completion(self):
        anchor = date(2026, 3, 14)
        dates = [anchor - timedelta(days=i) for i in range(2, 5)]

        streak = Streak.from_dates(dates, Frequency.DAILY, today=anchor)

        assert streak.is_active is False
        assert streak.current == 0
        assert streak.longest == 3

    def test_defaults_to_utc_not_the_local_clock(self):
        utc_today = datetime.now(UTC).date()

        assert Streak.from_dates([utc_today], Frequency.DAILY) == Streak.from_dates(
            [utc_today], Frequency.DAILY, today=utc_today
        )
