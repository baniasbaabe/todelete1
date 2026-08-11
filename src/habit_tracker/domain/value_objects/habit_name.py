from dataclasses import dataclass


@dataclass(frozen=True)
class HabitName:
    value: str

    def __post_init__(self) -> None:
        stripped = self.value.strip()
        if not stripped:
            raise ValueError("Habit name cannot be empty")
        if len(stripped) > 100:
            raise ValueError("Habit name cannot exceed 100 characters")
        object.__setattr__(self, "value", stripped)
