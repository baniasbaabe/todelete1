from __future__ import annotations

from habit_tracker.application.ports.repositories import (
    CompletionRepository,
    HabitRepository,
    UserRepository,
)
from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.exceptions import UserNotFoundError
from habit_tracker.domain.value_objects.streak import Streak
from habit_tracker.domain.value_objects.telegram_id import TelegramId


class ListHabits:
    def __init__(
        self,
        user_repo: UserRepository,
        habit_repo: HabitRepository,
        completion_repo: CompletionRepository,
    ) -> None:
        self._user_repo = user_repo
        self._habit_repo = habit_repo
        self._completion_repo = completion_repo

    async def execute(self, telegram_id: TelegramId) -> list[tuple[Habit, Streak]]:
        user = await self._user_repo.find_by_telegram_id(telegram_id)
        if user is None or user.id is None:
            raise UserNotFoundError(f"User with telegram_id {telegram_id.value} not found")

        habits = await self._habit_repo.find_active_by_user(user.id)
        dates_by_habit = await self._completion_repo.get_completion_dates_by_habits([
            h.id for h in habits if h.id is not None
        ])
        return [
            (habit, Streak.from_dates(dates_by_habit.get(habit.id, []), habit.frequency))
            for habit in habits
            if habit.id is not None
        ]
