from __future__ import annotations

from habit_tracker.application.ports.repositories import HabitRepository, UserRepository
from habit_tracker.domain.exceptions import HabitNotFoundError, UserNotFoundError
from habit_tracker.domain.value_objects.habit_name import HabitName
from habit_tracker.domain.value_objects.telegram_id import TelegramId


class DeleteHabit:
    def __init__(self, user_repo: UserRepository, habit_repo: HabitRepository) -> None:
        self._user_repo = user_repo
        self._habit_repo = habit_repo

    async def execute(self, telegram_id: TelegramId, name: HabitName) -> None:
        user = await self._user_repo.find_by_telegram_id(telegram_id)
        if user is None or user.id is None:
            raise UserNotFoundError(f"User with telegram_id {telegram_id.value} not found")

        habit = await self._habit_repo.find_active_by_user_and_name(user.id, name)
        if not habit:
            raise HabitNotFoundError(f"Habit '{name.value}' not found")

        habit.deactivate()
        await self._habit_repo.save(habit)
