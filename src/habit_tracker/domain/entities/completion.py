from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from habit_tracker.domain.value_objects.verification_policy import ProofType


@dataclass
class Completion:
    id: int | None
    habit_id: int
    completed_at: datetime
    proof_type: ProofType
    verified: bool
    verification_notes: str | None

    @classmethod
    def create(
        cls,
        habit_id: int,
        proof_type: ProofType,
        verified: bool,
        verification_notes: str | None = None,
    ) -> Completion:
        return cls(
            id=None,
            habit_id=habit_id,
            completed_at=datetime.now(UTC),
            proof_type=proof_type,
            verified=verified,
            verification_notes=verification_notes,
        )
