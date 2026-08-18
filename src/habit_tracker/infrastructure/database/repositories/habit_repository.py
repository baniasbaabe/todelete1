from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.exceptions import HabitAlreadyExistsError, HabitNotFoundError
from habit_tracker.domain.value_objects.frequency import Frequency
from habit_tracker.domain.value_objects.habit_name import HabitName
from habit_tracker.domain.value_objects.verification_policy import VerificationPolicy
from habit_tracker.infrastructure.database.models import ACTIVE_HABIT_NAME_INDEX, HabitModel


class SQLAlchemyHabitRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, habit: Habit) -> Habit:
        """Insert a new habit or update an existing one.

        An entity carrying an ID whose row has gone is an error, not an
        invitation to re-insert. The previous behaviour silently resurrected
        deleted rows under a fresh ID while the caller kept the stale one.
        """
        if habit.id is None:
            model = self._to_model(habit)
            self._session.add(model)
        else:
            model = await self._session.get(HabitModel, habit.id)
            if model is None:
                raise HabitNotFoundError(f"Habit {habit.id} no longer exists")
            model.user_id = habit.user_id
            model.name = habit.name.value
            model.description = habit.description
            model.frequency = habit.frequency.value
            model.verification_policy = habit.verification_policy.value
            model.is_active = habit.is_active
            model.created_at = habit.created_at

        try:
            await self._session.flush()
        except IntegrityError as exc:
            # CreateHabit checks for a duplicate first, but the check and the
            # insert are not atomic — two quick /add_habit messages can both
            # pass it. Anything else (a bad user_id, say) is not ours to
            # reinterpret, so it propagates untouched.
            if ACTIVE_HABIT_NAME_INDEX not in str(exc.orig):
                raise
            raise HabitAlreadyExistsError(f"Habit '{habit.name.value}' already exists") from exc

        habit.id = model.id
        return habit

    async def find_by_id(self, habit_id: int) -> Habit | None:
        model = await self._session.get(HabitModel, habit_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def find_active_by_user(self, user_id: int) -> list[Habit]:
        stmt = select(HabitModel).where(HabitModel.user_id == user_id, HabitModel.is_active.is_(True))
        result = await self._session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars().all()]

    async def find_active_by_user_and_name(self, user_id: int, name: HabitName) -> Habit | None:
        stmt = select(HabitModel).where(
            HabitModel.user_id == user_id,
            HabitModel.name == name.value,
            HabitModel.is_active.is_(True),
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_entity(model)

    async def delete(self, habit_id: int) -> None:
        model = await self._session.get(HabitModel, habit_id)
        if model is not None:
            await self._session.delete(model)
            await self._session.flush()

    def _to_entity(self, model: HabitModel) -> Habit:
        return Habit(
            id=model.id,
            user_id=model.user_id,
            name=HabitName(model.name),
            description=model.description,
            frequency=Frequency(model.frequency),
            verification_policy=VerificationPolicy(model.verification_policy),
            is_active=model.is_active,
            created_at=model.created_at,
        )

    def _to_model(self, habit: Habit) -> HabitModel:
        return HabitModel(
            user_id=habit.user_id,
            name=habit.name.value,
            description=habit.description,
            frequency=habit.frequency.value,
            verification_policy=habit.verification_policy.value,
            is_active=habit.is_active,
            created_at=habit.created_at,
        )
