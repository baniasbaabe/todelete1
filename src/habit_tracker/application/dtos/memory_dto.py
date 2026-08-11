from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class MemoryInsight:
    content: str
    category: str
    created_at: datetime
