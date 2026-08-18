from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from habit_tracker.domain.entities.completion import Completion
from habit_tracker.domain.exceptions import CompletionNotFoundError
from habit_tracker.domain.value_objects.verification_policy import ProofType
from habit_tracker.infrastructure.database.models import CompletionModel


class SQLAlchemyCompletionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, completion: Completion) -> Completion:
        """Insert a new completion or update an existing one.

        A missing row for a given ID raises rather than re-inserting, which
        would have resurrected a completion deleted along with its habit.
        """
        if completion.id is None:
            model = self._to_model(completion)
            self._session.add(model)
        else:
            model = await self._session.get(CompletionModel, completion.id)
            if model is None:
                raise CompletionNotFoundError(f"Completion {completion.id} no longer exists")
            model.habit_id = completion.habit_id
            model.completed_at = completion.completed_at
            model.proof_type = completion.proof_type.value
            model.verified = completion.verified
            model.verification_notes = completion.verification_notes

        await self._session.flush()
        completion.id = model.id
        return completion

    async def find_today_by_habits(self, habit_ids: list[int]) -> list[Completion]:
        if not habit_ids:
            return []
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        stmt = select(CompletionModel).where(
            CompletionModel.habit_id.in_(habit_ids),
            CompletionModel.completed_at >= today_start,
        )
        result = await self._session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars().all()]

    async def get_completion_dates(self, habit_id: int) -> list[date]:
        stmt = (
            select(func.date(CompletionModel.completed_at).label("completion_date"))
            .where(CompletionModel.habit_id == habit_id)
            .distinct()
            .order_by(func.date(CompletionModel.completed_at).desc())
        )
        result = await self._session.execute(stmt)
        return [row.completion_date for row in result.all()]

    async def get_completion_dates_by_habits(self, habit_ids: list[int]) -> dict[int, list[date]]:
        """Completion dates for many habits in one query, newest first per habit."""
        dates: dict[int, list[date]] = {habit_id: [] for habit_id in habit_ids}
        if not habit_ids:
            return dates

        completion_date = func.date(CompletionModel.completed_at).label("completion_date")
        stmt = (
            select(CompletionModel.habit_id, completion_date)
            .where(CompletionModel.habit_id.in_(habit_ids))
            .distinct()
            .order_by(CompletionModel.habit_id, completion_date.desc())
        )
        result = await self._session.execute(stmt)
        for row in result.all():
            dates[row.habit_id].append(row.completion_date)
        return dates

    async def find_by_habits_since(self, habit_ids: list[int], since: date) -> dict[int, list[Completion]]:
        """Completions for many habits since a cut-off, grouped by habit ID."""
        grouped: dict[int, list[Completion]] = {habit_id: [] for habit_id in habit_ids}
        if not habit_ids:
            return grouped

        since_dt = datetime(since.year, since.month, since.day, tzinfo=UTC)
        stmt = select(CompletionModel).where(
            CompletionModel.habit_id.in_(habit_ids),
            CompletionModel.completed_at >= since_dt,
        )
        result = await self._session.execute(stmt)
        for model in result.scalars().all():
            grouped[model.habit_id].append(self._to_entity(model))
        return grouped

    def _to_entity(self, model: CompletionModel) -> Completion:
        return Completion(
            id=model.id,
            habit_id=model.habit_id,
            completed_at=model.completed_at,
            proof_type=ProofType(model.proof_type),
            verified=model.verified,
            verification_notes=model.verification_notes,
        )

    def _to_model(self, completion: Completion) -> CompletionModel:
        return CompletionModel(
            habit_id=completion.habit_id,
            completed_at=completion.completed_at,
            proof_type=completion.proof_type.value,
            verified=completion.verified,
            verification_notes=completion.verification_notes,
        )
