from dataclasses import dataclass


@dataclass(frozen=True)
class HabitDTO:
    id: int
    name: str
    description: str | None
    frequency: str
    verification_policy: str
    is_active: bool
