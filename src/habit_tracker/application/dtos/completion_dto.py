from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CompletionDTO:
    id: int
    habit_id: int
    completed_at: datetime
    proof_type: str
    verified: bool
