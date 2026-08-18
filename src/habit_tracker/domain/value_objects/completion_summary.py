from dataclasses import dataclass


@dataclass(frozen=True)
class CompletionSummary:
    total: int
    completed: int

    @property
    def pending(self) -> int:
        return self.total - self.completed

    @property
    def completion_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.completed / self.total) * 100

    def get_encouragement(self) -> str:
        rate = self.completion_rate
        if rate >= 80:
            return "Outstanding! You're crushing it!"
        if rate >= 60:
            return "Great job! Keep up the momentum!"
        if rate > 0:
            return "Good start! Every habit counts!"
        return "Tomorrow is a new day! You've got this!"
