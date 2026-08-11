from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from habit_tracker.domain.value_objects.frequency import Frequency
from habit_tracker.domain.value_objects.habit_name import HabitName
from habit_tracker.domain.value_objects.verification_policy import VerificationPolicy


@dataclass
class Habit:
    id: int | None
    user_id: int
    name: HabitName
    description: str | None
    frequency: Frequency
    verification_policy: VerificationPolicy
    is_active: bool
    created_at: datetime

    @classmethod
    def create(
        cls,
        user_id: int,
        name: HabitName,
        description: str | None = None,
        frequency: Frequency = Frequency.DAILY,
        verification_policy: VerificationPolicy = VerificationPolicy.NONE,
    ) -> Habit:
        return cls(
            id=None,
            user_id=user_id,
            name=name,
            description=description,
            frequency=frequency,
            verification_policy=verification_policy,
            is_active=True,
            created_at=datetime.now(UTC),
        )

    def deactivate(self) -> None:
        self.is_active = False

    def requires_proof(self) -> bool:
        return self.verification_policy != VerificationPolicy.NONE
