from __future__ import annotations

from habit_tracker.application.ports.repositories import HabitRepository, UserRepository
from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.exceptions import HabitNotFoundError, UserNotFoundError
from habit_tracker.domain.value_objects.telegram_id import TelegramId
from habit_tracker.domain.value_objects.verification_policy import VerificationPolicy


class SetHabitVerification:
    def __init__(self, user_repo: UserRepository, habit_repo: HabitRepository) -> None:
        self._user_repo = user_repo
        self._habit_repo = habit_repo

    async def execute(self, telegram_id: TelegramId, habit_id: int, policy: VerificationPolicy) -> Habit:
        user = await self._user_repo.find_by_telegram_id(telegram_id)
        if user is None or user.id is None:
            raise UserNotFoundError(f"User with telegram_id {telegram_id.value} not found")
        habit = await self._habit_repo.find_by_id(habit_id)
        if habit is None or habit.user_id != user.id or not habit.is_active:
            raise HabitNotFoundError(f"Habit {habit_id} not found")
        habit.verification_policy = policy
        return await self._habit_repo.save(habit)
