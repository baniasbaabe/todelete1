from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from habit_tracker.domain.value_objects.frequency import Frequency


@dataclass(frozen=True)
class Streak:
    current: int
    longest: int
    is_active: bool

    @classmethod
    def from_dates(cls, dates: list[date], frequency: Frequency, today: date | None = None) -> Streak:
        """Compute a streak from completion dates.

        ``today`` defaults to the current UTC date because that is the clock the
        completion dates themselves were recorded against; a local
        ``date.today()`` put the two on different days for anyone far enough
        from Greenwich. It is injectable so tests can pin the boundary instead
        of racing midnight.
        """
        if not dates:
            return cls(current=0, longest=0, is_active=False)

        unique_sorted = sorted(set(dates), reverse=True)
        today = today or datetime.now(UTC).date()

        if frequency == Frequency.DAILY:
            return cls._compute_daily(unique_sorted, today)
        return cls._compute_weekly(unique_sorted, today)

    @classmethod
    def _compute_daily(cls, sorted_dates: list[date], today: date) -> Streak:
        is_active = sorted_dates[0] >= today - timedelta(days=1)

        streaks: list[int] = []
        run = 1
        for i in range(1, len(sorted_dates)):
            if (sorted_dates[i - 1] - sorted_dates[i]).days == 1:
                run += 1
            else:
                streaks.append(run)
                run = 1
        streaks.append(run)

        longest = max(streaks)
        current = streaks[0] if is_active else 0
        return cls(current=current, longest=longest, is_active=is_active)

    @classmethod
    def _compute_weekly(cls, sorted_dates: list[date], today: date) -> Streak:
        weeks = sorted({d.isocalendar()[:2] for d in sorted_dates}, reverse=True)
        this_week = today.isocalendar()[:2]
        last_week = (today - timedelta(weeks=1)).isocalendar()[:2]
        is_active = weeks[0] in (this_week, last_week)

        streaks: list[int] = []
        run = 1
        for i in range(1, len(weeks)):
            prev_monday = date.fromisocalendar(weeks[i - 1][0], weeks[i - 1][1], 1)
            curr_monday = date.fromisocalendar(weeks[i][0], weeks[i][1], 1)
            if (prev_monday - curr_monday).days == 7:
                run += 1
            else:
                streaks.append(run)
                run = 1
        streaks.append(run)

        longest = max(streaks)
        current = streaks[0] if is_active else 0
        return cls(current=current, longest=longest, is_active=is_active)
