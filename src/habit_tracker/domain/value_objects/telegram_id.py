from dataclasses import dataclass


@dataclass(frozen=True)
class TelegramId:
    value: int

    def __post_init__(self) -> None:
        if self.value <= 0:
            raise ValueError("Telegram ID must be positive")
