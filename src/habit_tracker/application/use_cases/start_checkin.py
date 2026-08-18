from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from habit_tracker.application.dtos.pattern_dto import CheckinContext
from habit_tracker.application.ports.ai_services import PatternAnalyzer
from habit_tracker.application.ports.repositories import (
    CompletionRepository,
    HabitRepository,
    UserRepository,
)
from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.exceptions import UserNotFoundError
from habit_tracker.domain.value_objects.frequency import Frequency
from habit_tracker.domain.value_objects.telegram_id import TelegramId


@dataclass(frozen=True)
class CheckinStart:
    """Everything the caller needs to open a check-in session.

    ``user_id`` is the persistent user ID, not the Telegram ID: memory insights
    are stored and retrieved under it, so the two must not diverge.
    """

    user_id: int
    pending: list[Habit]
    coaching: str


HISTORY_DAYS = 30


class StartCheckin:
    def __init__(
        self,
        user_repo: UserRepository,
        habit_repo: HabitRepository,
        completion_repo: CompletionRepository,
        pattern_analyzer: PatternAnalyzer,
    ) -> None:
        self._user_repo = user_repo
        self._habit_repo = habit_repo
        self._completion_repo = completion_repo
        self._pattern_analyzer = pattern_analyzer

    async def execute(self, telegram_id: TelegramId) -> CheckinStart:
        user = await self._user_repo.find_by_telegram_id(telegram_id)
        if user is None or user.id is None:
            raise UserNotFoundError(f"User with telegram_id {telegram_id.value} not found")

        habits = await self._habit_repo.find_active_by_user(user.id)
        if not habits:
            return CheckinStart(user.id, [], "No active habits. Create one with /add_habit!")

        habit_ids = [h.id for h in habits if h.id is not None]
        today_completions = await self._completion_repo.find_today_by_habits(habit_ids)
        completed_ids = {c.habit_id for c in today_completions}
        pending = [h for h in habits if h.id not in completed_ids]

        if not pending:
            return CheckinStart(user.id, [], "All habits completed for today! Great job!")

        # Completions are stamped in UTC, so the history window has to be
        # measured in UTC too — a local date.today() moved the cut-off by up to
        # a day depending on where the process happened to be running.
        since = datetime.now(UTC).date() - timedelta(days=HISTORY_DAYS)
        recent = await self._completion_repo.find_by_habits_since(habit_ids, since)
        completions_by_habit = {
            habit.name.value: recent.get(habit.id, [])
            for habit in habits
            if habit.id is not None and habit.frequency is Frequency.DAILY
        }

        patterns = await self._pattern_analyzer.analyze_patterns(user.id, completions_by_habit)
        context = CheckinContext(habits=pending, today_completions=today_completions, patterns=patterns)
        coaching = await self._pattern_analyzer.generate_coaching_message(user.id, patterns, context)

        return CheckinStart(user.id, pending, coaching)
