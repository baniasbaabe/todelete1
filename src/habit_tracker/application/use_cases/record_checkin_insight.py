from __future__ import annotations

from datetime import datetime

from habit_tracker.application.checkin_session import CheckinResult
from habit_tracker.application.ports.ai_services import MemoryStore

INSIGHT_CATEGORY = "checkin"


class RecordCheckinInsight:
    """Persist a summary of a finished check-in to long-term memory.

    This is the write half of the memory feature: ``LLMPatternAnalyzer`` reads
    these back through ``MemoryStore.get_insights`` when composing the next
    coaching message, so without it every check-in is coached blind.

    One insight is stored per completed session rather than one per habit, to
    keep the vector store dense enough to stay useful as it grows.
    """

    def __init__(self, memory_store: MemoryStore) -> None:
        self._memory = memory_store

    async def execute(self, user_id: int, results: list[CheckinResult], occurred_at: datetime) -> None:
        """Store one insight for a finished session. Never raises.

        Args:
            user_id: Persistent user ID — must match the ID used for reads,
                not the Telegram ID.
            results: Per-habit outcomes collected during the session.
            occurred_at: When the session started, so the LLM can reason about
                recency rather than treating every insight as equally current.
        """
        if not results:
            return

        completed = [r.habit_name for r in results if r.completed]
        skipped = [r.habit_name for r in results if not r.completed]

        parts = []
        if completed:
            parts.append(f"completed {', '.join(completed)}")
        if skipped:
            parts.append(f"skipped {', '.join(skipped)}")

        insight = f"On {occurred_at.date().isoformat()} the user {' and '.join(parts)}."
        await self._memory.store_insight(user_id, insight, INSIGHT_CATEGORY)
