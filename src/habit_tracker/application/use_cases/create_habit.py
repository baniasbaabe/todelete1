from __future__ import annotations

from habit_tracker.application.ports.repositories import HabitRepository, UserRepository
from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.exceptions import HabitAlreadyExistsError, UserNotFoundError
from habit_tracker.domain.value_objects.frequency import Frequency
from habit_tracker.domain.value_objects.habit_name import HabitName
from habit_tracker.domain.value_objects.telegram_id import TelegramId
from habit_tracker.domain.value_objects.verification_policy import VerificationPolicy


class CreateHabit:
    def __init__(self, user_repo: UserRepository, habit_repo: HabitRepository) -> None:
        self._user_repo = user_repo
        self._habit_repo = habit_repo

    async def execute(
        self,
        telegram_id: TelegramId,
        name: HabitName,
        description: str | None = None,
        frequency: Frequency = Frequency.DAILY,
        verification_policy: VerificationPolicy = VerificationPolicy.NONE,
    ) -> Habit:
        user = await self._user_repo.find_by_telegram_id(telegram_id)
        if user is None or user.id is None:
            raise UserNotFoundError(f"User with telegram_id {telegram_id.value} not found")

        existing = await self._habit_repo.find_active_by_user_and_name(user.id, name)
        if existing:
            raise HabitAlreadyExistsError(f"Habit '{name.value}' already exists")

        habit = Habit.create(user.id, name, description, frequency, verification_policy)
        return await self._habit_repo.save(habit)
