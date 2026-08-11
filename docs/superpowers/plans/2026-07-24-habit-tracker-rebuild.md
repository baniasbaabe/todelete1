# AI Habit Tracker — Full Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Telegram habit tracker bot from scratch with proper Clean Architecture, rich domain model, provider-agnostic LLM via LiteLLM, mem0 memory, configurable proof verification, and full test coverage.

**Architecture:** Classical layered Clean Architecture (domain ← application ← infrastructure/presentation). Dependency inversion via Protocol interfaces in the application layer, constructor injection, no DI library. Conversation state managed by a `CheckinSession` dataclass persisted to PostgreSQL via python-telegram-bot's `BasePersistence`.

**Tech Stack:** Python 3.13, uv, python-telegram-bot (webhooks), SQLAlchemy 2.0 async, asyncpg, PostgreSQL 17 + pgvector, LiteLLM, mem0, Arize Phoenix, structlog, Terragrunt/OpenTofu, GitHub Actions

## Global Constraints

- Python >= 3.13, managed by uv
- Clean Architecture dependency rule: domain has zero imports from other layers; application imports only domain; infrastructure/presentation import application+domain
- All protocols use `typing.Protocol`, no ABCs
- All entities are mutable dataclasses with factory classmethods; all value objects are `frozen=True` dataclasses or enums
- No `missed` column or synthetic backfill data — gaps computed on-the-fly
- Single `DATABASE_URL` env var for app, mem0, and alembic
- Settings evaluated at construction time (`__init__`), never at class/module level
- Tests organized by type: `tests/unit/` (pure Python, no IO) and `tests/integration/` (testcontainers + VCR)
- Every task ends with passing tests and a git commit

**Spec:** `docs/superpowers/specs/2026-07-23-habit-tracker-rebuild-design.md`

---

### Task 1: Project Setup + Domain Value Objects & Exceptions

**Files:**
- Modify: `pyproject.toml`
- Create: `src/habit_tracker/__init__.py`
- Create: `src/habit_tracker/domain/__init__.py`
- Create: `src/habit_tracker/domain/value_objects/__init__.py`
- Create: `src/habit_tracker/domain/value_objects/telegram_id.py`
- Create: `src/habit_tracker/domain/value_objects/habit_name.py`
- Create: `src/habit_tracker/domain/value_objects/frequency.py`
- Create: `src/habit_tracker/domain/value_objects/verification_policy.py`
- Create: `src/habit_tracker/domain/value_objects/proof_result.py`
- Create: `src/habit_tracker/domain/value_objects/streak.py`
- Create: `src/habit_tracker/domain/value_objects/completion_summary.py`
- Create: `src/habit_tracker/domain/exceptions.py`
- Create: `tests/unit/test_value_objects.py`
- Create: `tests/unit/test_streak.py`
- Create: `tests/unit/test_completion_summary.py`
- Create: `pyproject.toml` (pytest config section)

**Interfaces:**
- Consumes: nothing (first task)
- Produces: `TelegramId`, `HabitName`, `Frequency`, `VerificationPolicy`, `ProofType`, `ProofResult`, `Streak`, `CompletionSummary`, all domain exceptions — used by every subsequent task

- [ ] **Step 1: Remove old source code and set up new directory structure**

```bash
rm -rf src/habit_tracker/application src/habit_tracker/domain src/habit_tracker/infrastructure src/habit_tracker/presentation
mkdir -p src/habit_tracker/domain/{entities,value_objects}
mkdir -p src/habit_tracker/application/{ports,dtos,use_cases}
mkdir -p src/habit_tracker/infrastructure/{ai,memory,database/repositories,persistence,observability,config,logging}
mkdir -p src/habit_tracker/presentation/handlers
mkdir -p tests/{unit,integration/cassettes}
```

- [ ] **Step 2: Update pyproject.toml with new dependencies and test config**

```toml
[project]
name = "habit-tracker"
version = "0.1.0"
description = "AI-powered Telegram habit tracker with Clean Architecture"
requires-python = ">=3.13"
dependencies = [
    "python-telegram-bot[webhooks]",
    "sqlalchemy[asyncio]",
    "asyncpg",
    "litellm",
    "mem0ai",
    "arize-phoenix-otel",
    "openinference-instrumentation-litellm",
    "structlog",
    "alembic",
    "psycopg2-binary",
    "python-dotenv",
    "greenlet",
]

[dependency-groups]
dev = [
    "pytest",
    "pytest-asyncio",
    "pytest-env",
    "pytest-xdist",
    "testcontainers[postgres]",
    "vcrpy",
    "prek",
]

[project.scripts]
habit-tracker = "habit_tracker:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.backends"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
env = [
    "TELEGRAM_BOT_TOKEN=test-token",
    "DATABASE_URL=postgresql+asyncpg://test:test@localhost:5432/test",
    "LLM_MODEL=gpt-4o-mini",
    "LLM_TEMPERATURE=0.0",
    "WEBHOOK_URL=https://test.example.com/webhook",
    "ENABLE_TRACING=false",
]
```

Run: `uv sync`

- [ ] **Step 3: Write failing tests for TelegramId and HabitName**

```python
# tests/unit/test_value_objects.py
import pytest

from habit_tracker.domain.value_objects.telegram_id import TelegramId
from habit_tracker.domain.value_objects.habit_name import HabitName


class TestTelegramId:
    def test_valid_id(self):
        tid = TelegramId(123456)
        assert tid.value == 123456

    def test_zero_raises(self):
        with pytest.raises(ValueError, match="positive"):
            TelegramId(0)

    def test_negative_raises(self):
        with pytest.raises(ValueError, match="positive"):
            TelegramId(-1)

    def test_equality(self):
        assert TelegramId(42) == TelegramId(42)

    def test_immutable(self):
        tid = TelegramId(1)
        with pytest.raises(AttributeError):
            tid.value = 2


class TestHabitName:
    def test_valid_name(self):
        name = HabitName("Read 30 min")
        assert name.value == "Read 30 min"

    def test_strips_whitespace(self):
        name = HabitName("  gym  ")
        assert name.value == "gym"

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            HabitName("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="empty"):
            HabitName("   ")

    def test_too_long_raises(self):
        with pytest.raises(ValueError, match="100"):
            HabitName("x" * 101)

    def test_max_length_ok(self):
        name = HabitName("x" * 100)
        assert len(name.value) == 100

    def test_equality(self):
        assert HabitName("gym") == HabitName("gym")
```

Run: `uv run pytest tests/unit/test_value_objects.py -v`
Expected: FAIL — modules not found

- [ ] **Step 4: Implement TelegramId, HabitName, enums, ProofResult**

```python
# src/habit_tracker/domain/value_objects/telegram_id.py
from dataclasses import dataclass


@dataclass(frozen=True)
class TelegramId:
    value: int

    def __post_init__(self) -> None:
        if self.value <= 0:
            raise ValueError("Telegram ID must be positive")
```

```python
# src/habit_tracker/domain/value_objects/habit_name.py
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
```

```python
# src/habit_tracker/domain/value_objects/frequency.py
from enum import StrEnum


class Frequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
```

```python
# src/habit_tracker/domain/value_objects/verification_policy.py
from enum import StrEnum


class VerificationPolicy(StrEnum):
    NONE = "none"
    TEXT = "text"
    PHOTO = "photo"


class ProofType(StrEnum):
    NONE = "none"
    TEXT = "text"
    PHOTO = "photo"
```

```python
# src/habit_tracker/domain/value_objects/proof_result.py
from dataclasses import dataclass


@dataclass(frozen=True)
class ProofResult:
    verified: bool
    confidence: float
    reasoning: str
```

```python
# src/habit_tracker/domain/value_objects/__init__.py
from .completion_summary import CompletionSummary
from .frequency import Frequency
from .habit_name import HabitName
from .proof_result import ProofResult
from .streak import Streak
from .telegram_id import TelegramId
from .verification_policy import ProofType, VerificationPolicy

__all__ = [
    "CompletionSummary",
    "Frequency",
    "HabitName",
    "ProofResult",
    "ProofType",
    "Streak",
    "TelegramId",
    "VerificationPolicy",
]
```

Run: `uv run pytest tests/unit/test_value_objects.py -v`
Expected: PASS (Streak and CompletionSummary not yet imported but __init__ will fail — create stubs first, see next steps)

- [ ] **Step 5: Write failing tests for Streak**

```python
# tests/unit/test_streak.py
from datetime import date, timedelta

from habit_tracker.domain.value_objects.frequency import Frequency
from habit_tracker.domain.value_objects.streak import Streak


class TestDailyStreak:
    def test_no_dates(self):
        streak = Streak.from_dates([], Frequency.DAILY)
        assert streak.current == 0
        assert streak.longest == 0
        assert streak.is_active is False

    def test_single_date_today(self):
        streak = Streak.from_dates([date.today()], Frequency.DAILY)
        assert streak.current == 1
        assert streak.longest == 1
        assert streak.is_active is True

    def test_single_date_yesterday(self):
        streak = Streak.from_dates([date.today() - timedelta(days=1)], Frequency.DAILY)
        assert streak.current == 1
        assert streak.longest == 1
        assert streak.is_active is True

    def test_single_date_two_days_ago(self):
        streak = Streak.from_dates([date.today() - timedelta(days=2)], Frequency.DAILY)
        assert streak.current == 0
        assert streak.longest == 1
        assert streak.is_active is False

    def test_consecutive_days(self):
        today = date.today()
        dates = [today - timedelta(days=i) for i in range(5)]
        streak = Streak.from_dates(dates, Frequency.DAILY)
        assert streak.current == 5
        assert streak.longest == 5
        assert streak.is_active is True

    def test_gap_breaks_current_but_not_longest(self):
        today = date.today()
        dates = [today, today - timedelta(days=1)]
        old = [today - timedelta(days=10 + i) for i in range(7)]
        streak = Streak.from_dates(dates + old, Frequency.DAILY)
        assert streak.current == 2
        assert streak.longest == 7

    def test_duplicate_dates_ignored(self):
        today = date.today()
        dates = [today, today, today - timedelta(days=1), today - timedelta(days=1)]
        streak = Streak.from_dates(dates, Frequency.DAILY)
        assert streak.current == 2

    def test_unordered_input(self):
        today = date.today()
        dates = [today - timedelta(days=2), today, today - timedelta(days=1)]
        streak = Streak.from_dates(dates, Frequency.DAILY)
        assert streak.current == 3


class TestWeeklyStreak:
    def test_no_dates(self):
        streak = Streak.from_dates([], Frequency.WEEKLY)
        assert streak.current == 0
        assert streak.is_active is False

    def test_completion_this_week(self):
        streak = Streak.from_dates([date.today()], Frequency.WEEKLY)
        assert streak.current == 1
        assert streak.is_active is True

    def test_consecutive_weeks(self):
        today = date.today()
        dates = [today - timedelta(weeks=i) for i in range(4)]
        streak = Streak.from_dates(dates, Frequency.WEEKLY)
        assert streak.current == 4
        assert streak.longest == 4
```

Run: `uv run pytest tests/unit/test_streak.py -v`
Expected: FAIL — Streak not implemented

- [ ] **Step 6: Implement Streak**

```python
# src/habit_tracker/domain/value_objects/streak.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from habit_tracker.domain.value_objects.frequency import Frequency


@dataclass(frozen=True)
class Streak:
    current: int
    longest: int
    is_active: bool

    @classmethod
    def from_dates(cls, dates: list[date], frequency: Frequency) -> Streak:
        if not dates:
            return cls(current=0, longest=0, is_active=False)

        unique_sorted = sorted(set(dates), reverse=True)
        today = date.today()

        if frequency == Frequency.DAILY:
            return cls._compute_daily(unique_sorted, today)
        return cls._compute_weekly(unique_sorted, today)

    @classmethod
    def _compute_daily(cls, sorted_dates: list[date], today: date) -> Streak:
        is_active = sorted_dates[0] >= today - timedelta(days=1)

        streaks: list[int] = []
        run = 1
        for i in range(1, len(sorted_dates)):
            if (sorted_dates[i - 1] - sorted_dates[i]).days == 1:
                run += 1
            else:
                streaks.append(run)
                run = 1
        streaks.append(run)

        longest = max(streaks)
        current = streaks[0] if is_active else 0
        return cls(current=current, longest=longest, is_active=is_active)

    @classmethod
    def _compute_weekly(cls, sorted_dates: list[date], today: date) -> Streak:
        weeks = sorted(
            {d.isocalendar()[:2] for d in sorted_dates}, reverse=True
        )
        this_week = today.isocalendar()[:2]
        last_week = (today - timedelta(weeks=1)).isocalendar()[:2]
        is_active = weeks[0] in (this_week, last_week)

        streaks: list[int] = []
        run = 1
        for i in range(1, len(weeks)):
            prev_monday = date.fromisocalendar(weeks[i - 1][0], weeks[i - 1][1], 1)
            curr_monday = date.fromisocalendar(weeks[i][0], weeks[i][1], 1)
            if (prev_monday - curr_monday).days == 7:
                run += 1
            else:
                streaks.append(run)
                run = 1
        streaks.append(run)

        longest = max(streaks)
        current = streaks[0] if is_active else 0
        return cls(current=current, longest=longest, is_active=is_active)
```

Run: `uv run pytest tests/unit/test_streak.py -v`
Expected: PASS

- [ ] **Step 7: Write failing tests for CompletionSummary**

```python
# tests/unit/test_completion_summary.py
from habit_tracker.domain.value_objects.completion_summary import CompletionSummary


class TestCompletionSummary:
    def test_all_completed(self):
        s = CompletionSummary(total=5, completed=5)
        assert s.pending == 0
        assert s.completion_rate == 100.0

    def test_none_completed(self):
        s = CompletionSummary(total=3, completed=0)
        assert s.pending == 3
        assert s.completion_rate == 0.0

    def test_partial(self):
        s = CompletionSummary(total=4, completed=3)
        assert s.pending == 1
        assert s.completion_rate == 75.0

    def test_empty(self):
        s = CompletionSummary(total=0, completed=0)
        assert s.completion_rate == 0.0

    def test_encouragement_excellent(self):
        s = CompletionSummary(total=5, completed=5)
        assert "crushing" in s.get_encouragement().lower() or "outstanding" in s.get_encouragement().lower()

    def test_encouragement_zero(self):
        s = CompletionSummary(total=5, completed=0)
        assert "tomorrow" in s.get_encouragement().lower() or "got this" in s.get_encouragement().lower()
```

- [ ] **Step 8: Implement CompletionSummary**

```python
# src/habit_tracker/domain/value_objects/completion_summary.py
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
```

- [ ] **Step 9: Implement domain exceptions**

```python
# src/habit_tracker/domain/exceptions.py
class HabitTrackerError(Exception):
    pass


class UserNotFoundError(HabitTrackerError):
    pass


class HabitNotFoundError(HabitTrackerError):
    pass


class HabitAlreadyExistsError(HabitTrackerError):
    pass


class HabitLimitExceededError(HabitTrackerError):
    pass


class InvalidProofTypeError(HabitTrackerError):
    pass


class ConfigurationError(HabitTrackerError):
    pass
```

```python
# src/habit_tracker/domain/__init__.py
```

```python
# src/habit_tracker/__init__.py
import asyncio


def main() -> None:
    from habit_tracker.presentation.main import async_main

    asyncio.run(async_main())
```

- [ ] **Step 10: Run all unit tests, verify green, commit**

Run: `uv run pytest tests/unit/ -v`
Expected: all tests PASS

```bash
git add src/habit_tracker/domain/ tests/unit/ pyproject.toml
git commit -m "feat: add domain value objects, streak, completion summary, exceptions"
```

---

### Task 2: Domain Entities

**Files:**
- Create: `src/habit_tracker/domain/entities/__init__.py`
- Create: `src/habit_tracker/domain/entities/user.py`
- Create: `src/habit_tracker/domain/entities/habit.py`
- Create: `src/habit_tracker/domain/entities/completion.py`
- Create: `tests/unit/test_habit.py`

**Interfaces:**
- Consumes: `TelegramId`, `HabitName`, `Frequency`, `VerificationPolicy`, `ProofType` from Task 1
- Produces: `User`, `Habit`, `Completion` entities — used by use cases, repositories, handlers

- [ ] **Step 1: Write failing tests for Habit entity**

```python
# tests/unit/test_habit.py
import pytest

from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.value_objects import (
    Frequency,
    HabitName,
    ProofType,
    VerificationPolicy,
)


class TestHabitCreate:
    def test_creates_with_defaults(self):
        habit = Habit.create(user_id=1, name=HabitName("gym"))
        assert habit.id is None
        assert habit.user_id == 1
        assert habit.name == HabitName("gym")
        assert habit.frequency == Frequency.DAILY
        assert habit.verification_policy == VerificationPolicy.NONE
        assert habit.is_active is True

    def test_creates_with_photo_policy(self):
        habit = Habit.create(
            user_id=1,
            name=HabitName("gym"),
            verification_policy=VerificationPolicy.PHOTO,
        )
        assert habit.verification_policy == VerificationPolicy.PHOTO


class TestHabitBehavior:
    def test_deactivate(self):
        habit = Habit.create(user_id=1, name=HabitName("gym"))
        habit.deactivate()
        assert habit.is_active is False

    def test_requires_proof_none(self):
        habit = Habit.create(user_id=1, name=HabitName("gym"))
        assert habit.requires_proof() is False

    def test_requires_proof_text(self):
        habit = Habit.create(
            user_id=1,
            name=HabitName("read"),
            verification_policy=VerificationPolicy.TEXT,
        )
        assert habit.requires_proof() is True

    def test_requires_proof_photo(self):
        habit = Habit.create(
            user_id=1,
            name=HabitName("gym"),
            verification_policy=VerificationPolicy.PHOTO,
        )
        assert habit.requires_proof() is True

    def test_accepts_matching_proof_type(self):
        habit = Habit.create(
            user_id=1,
            name=HabitName("gym"),
            verification_policy=VerificationPolicy.PHOTO,
        )
        assert habit.accepts_proof_type(ProofType.PHOTO) is True
        assert habit.accepts_proof_type(ProofType.TEXT) is False

    def test_none_policy_accepts_none_proof(self):
        habit = Habit.create(user_id=1, name=HabitName("meditate"))
        assert habit.accepts_proof_type(ProofType.NONE) is True
        assert habit.accepts_proof_type(ProofType.TEXT) is False
```

Run: `uv run pytest tests/unit/test_habit.py -v`
Expected: FAIL — module not found

- [ ] **Step 2: Implement User, Habit, Completion entities**

```python
# src/habit_tracker/domain/entities/user.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from habit_tracker.domain.value_objects.telegram_id import TelegramId


@dataclass
class User:
    id: int | None
    telegram_id: TelegramId
    username: str | None
    created_at: datetime

    @classmethod
    def create(cls, telegram_id: TelegramId, username: str | None = None) -> User:
        return cls(
            id=None,
            telegram_id=telegram_id,
            username=username,
            created_at=datetime.now(timezone.utc),
        )

    def is_persisted(self) -> bool:
        return self.id is not None
```

```python
# src/habit_tracker/domain/entities/habit.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from habit_tracker.domain.value_objects.frequency import Frequency
from habit_tracker.domain.value_objects.habit_name import HabitName
from habit_tracker.domain.value_objects.verification_policy import (
    ProofType,
    VerificationPolicy,
)


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
            created_at=datetime.now(timezone.utc),
        )

    def deactivate(self) -> None:
        self.is_active = False

    def requires_proof(self) -> bool:
        return self.verification_policy != VerificationPolicy.NONE

    def accepts_proof_type(self, proof_type: ProofType) -> bool:
        return proof_type.value == self.verification_policy.value
```

```python
# src/habit_tracker/domain/entities/completion.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

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
            completed_at=datetime.now(timezone.utc),
            proof_type=proof_type,
            verified=verified,
            verification_notes=verification_notes,
        )
```

```python
# src/habit_tracker/domain/entities/__init__.py
from .completion import Completion
from .habit import Habit
from .user import User

__all__ = ["Completion", "Habit", "User"]
```

- [ ] **Step 3: Run tests, verify green, commit**

Run: `uv run pytest tests/unit/test_habit.py tests/unit/test_value_objects.py tests/unit/test_streak.py tests/unit/test_completion_summary.py -v`
Expected: all PASS

```bash
git add src/habit_tracker/domain/entities/ tests/unit/test_habit.py
git commit -m "feat: add domain entities — User, Habit, Completion"
```

---

### Task 3: Application Ports, DTOs & CheckinSession

**Files:**
- Create: `src/habit_tracker/application/__init__.py`
- Create: `src/habit_tracker/application/ports/__init__.py`
- Create: `src/habit_tracker/application/ports/repositories.py`
- Create: `src/habit_tracker/application/ports/ai_services.py`
- Create: `src/habit_tracker/application/dtos/__init__.py`
- Create: `src/habit_tracker/application/dtos/habit_dto.py`
- Create: `src/habit_tracker/application/dtos/completion_dto.py`
- Create: `src/habit_tracker/application/dtos/memory_dto.py`
- Create: `src/habit_tracker/application/dtos/pattern_dto.py`
- Create: `src/habit_tracker/application/checkin_session.py`
- Create: `tests/unit/test_checkin_session.py`

**Interfaces:**
- Consumes: all domain entities and value objects from Tasks 1-2
- Produces: `UserRepository`, `HabitRepository`, `CompletionRepository`, `ProofVerifier`, `MemoryStore`, `PatternAnalyzer` protocols; all DTOs; `CheckinSession`, `SessionState`, `CheckinResult` — used by use cases (Task 4), infrastructure adapters (Tasks 5-8), handlers (Task 9)

- [ ] **Step 1: Create ports (Protocol interfaces)**

```python
# src/habit_tracker/application/ports/repositories.py
from __future__ import annotations

from datetime import date
from typing import Protocol

from habit_tracker.domain.entities.completion import Completion
from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.entities.user import User
from habit_tracker.domain.value_objects.habit_name import HabitName
from habit_tracker.domain.value_objects.telegram_id import TelegramId


class UserRepository(Protocol):
    async def save(self, user: User) -> User: ...
    async def find_by_telegram_id(self, telegram_id: TelegramId) -> User | None: ...


class HabitRepository(Protocol):
    async def save(self, habit: Habit) -> Habit: ...
    async def find_by_id(self, habit_id: int) -> Habit | None: ...
    async def find_active_by_user(self, user_id: int) -> list[Habit]: ...
    async def find_by_user_and_name(self, user_id: int, name: HabitName) -> Habit | None: ...
    async def delete(self, habit_id: int) -> None: ...


class CompletionRepository(Protocol):
    async def save(self, completion: Completion) -> Completion: ...
    async def find_today_by_habits(self, habit_ids: list[int]) -> list[Completion]: ...
    async def get_completion_dates(self, habit_id: int) -> list[date]: ...
    async def find_by_habit_since(self, habit_id: int, since: date) -> list[Completion]: ...
```

Note: spec says `find_today_by_user(user_id)` but changed to `find_today_by_habits(habit_ids)` — avoids a JOIN and makes in-memory fakes trivial. Use cases already have habit IDs from `find_active_by_user`.

```python
# src/habit_tracker/application/ports/ai_services.py
from __future__ import annotations

from typing import Protocol

from habit_tracker.application.dtos.memory_dto import MemoryInsight
from habit_tracker.application.dtos.pattern_dto import BehavioralPattern, CheckinContext
from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.value_objects.proof_result import ProofResult


class ProofVerifier(Protocol):
    async def verify_text(self, habit: Habit, proof_text: str) -> ProofResult: ...
    async def verify_image(self, habit: Habit, image_bytes: bytes) -> ProofResult: ...


class MemoryStore(Protocol):
    async def store_insight(self, user_id: int, insight: str, category: str) -> None: ...
    async def get_insights(self, user_id: int) -> list[MemoryInsight]: ...


class PatternAnalyzer(Protocol):
    async def analyze_patterns(
        self, user_id: int, completions: dict[str, list]
    ) -> list[BehavioralPattern]: ...
    async def generate_coaching_message(
        self, user_id: int, patterns: list[BehavioralPattern], context: CheckinContext
    ) -> str: ...
```

```python
# src/habit_tracker/application/ports/__init__.py
```

- [ ] **Step 2: Create DTOs**

```python
# src/habit_tracker/application/dtos/habit_dto.py
from dataclasses import dataclass


@dataclass(frozen=True)
class HabitDTO:
    id: int
    name: str
    description: str | None
    frequency: str
    verification_policy: str
    is_active: bool
```

```python
# src/habit_tracker/application/dtos/completion_dto.py
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CompletionDTO:
    id: int
    habit_id: int
    completed_at: datetime
    proof_type: str
    verified: bool
```

```python
# src/habit_tracker/application/dtos/memory_dto.py
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class MemoryInsight:
    content: str
    category: str
    created_at: datetime
```

```python
# src/habit_tracker/application/dtos/pattern_dto.py
from __future__ import annotations

from dataclasses import dataclass

from habit_tracker.domain.entities.completion import Completion
from habit_tracker.domain.entities.habit import Habit


@dataclass(frozen=True)
class BehavioralPattern:
    pattern_type: str
    description: str
    habit_name: str | None
    confidence: float


@dataclass(frozen=True)
class CheckinContext:
    habits: list[Habit]
    today_completions: list[Completion]
    patterns: list[BehavioralPattern]
```

```python
# src/habit_tracker/application/dtos/__init__.py
```

```python
# src/habit_tracker/application/__init__.py
```

- [ ] **Step 3: Write failing tests for CheckinSession**

```python
# tests/unit/test_checkin_session.py
from datetime import datetime, timedelta, timezone

import pytest

from habit_tracker.application.checkin_session import (
    CheckinSession,
    SessionState,
)
from habit_tracker.domain.entities.completion import Completion
from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.value_objects import HabitName, ProofType


def _make_habit(name: str, habit_id: int = 1) -> Habit:
    habit = Habit.create(user_id=1, name=HabitName(name))
    habit.id = habit_id
    return habit


class TestCheckinSession:
    def test_initial_state(self):
        habits = [_make_habit("gym", 1), _make_habit("read", 2)]
        session = CheckinSession.start(user_id=1, habits=habits)
        assert session.state == SessionState.AWAITING_RESPONSE
        assert session.current_habit() == habits[0]
        assert session.is_complete() is False

    def test_advance_to_next_habit(self):
        habits = [_make_habit("gym", 1), _make_habit("read", 2)]
        session = CheckinSession.start(user_id=1, habits=habits)
        session.record_skip()
        next_habit = session.advance()
        assert next_habit == habits[1]
        assert session.state == SessionState.AWAITING_RESPONSE

    def test_advance_past_last_habit(self):
        session = CheckinSession.start(user_id=1, habits=[_make_habit("gym", 1)])
        session.record_skip()
        next_habit = session.advance()
        assert next_habit is None
        assert session.is_complete() is True
        assert session.state == SessionState.DONE

    def test_record_completion(self):
        session = CheckinSession.start(user_id=1, habits=[_make_habit("gym", 1)])
        completion = Completion.create(habit_id=1, proof_type=ProofType.NONE, verified=True)
        session.record_completion(completion)
        summary = session.get_summary()
        assert summary.total == 1
        assert summary.completed == 1

    def test_set_awaiting_proof(self):
        session = CheckinSession.start(user_id=1, habits=[_make_habit("gym", 1)])
        session.state = SessionState.AWAITING_PROOF
        assert session.state == SessionState.AWAITING_PROOF

    def test_expired_after_24h(self):
        session = CheckinSession.start(user_id=1, habits=[_make_habit("gym", 1)])
        session.created_at = datetime.now(timezone.utc) - timedelta(hours=25)
        assert session.is_expired() is True

    def test_not_expired_within_24h(self):
        session = CheckinSession.start(user_id=1, habits=[_make_habit("gym", 1)])
        assert session.is_expired() is False

    def test_serialization_roundtrip(self):
        habits = [_make_habit("gym", 1), _make_habit("read", 2)]
        session = CheckinSession.start(user_id=1, habits=habits)
        session.record_skip()
        session.advance()

        data = session.to_dict()
        restored = CheckinSession.from_dict(data)

        assert restored.user_id == session.user_id
        assert restored.current_index == session.current_index
        assert restored.state == session.state
        assert len(restored.habits) == len(session.habits)
```

Run: `uv run pytest tests/unit/test_checkin_session.py -v`
Expected: FAIL

- [ ] **Step 4: Implement CheckinSession**

```python
# src/habit_tracker/application/checkin_session.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from habit_tracker.domain.entities.completion import Completion
from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.value_objects.completion_summary import CompletionSummary
from habit_tracker.domain.value_objects.frequency import Frequency
from habit_tracker.domain.value_objects.habit_name import HabitName
from habit_tracker.domain.value_objects.verification_policy import (
    ProofType,
    VerificationPolicy,
)

TTL_HOURS = 24


class SessionState(StrEnum):
    AWAITING_RESPONSE = "awaiting_response"
    AWAITING_PROOF = "awaiting_proof"
    DONE = "done"


@dataclass
class CheckinResult:
    habit_name: str
    completed: bool
    skipped: bool


@dataclass
class CheckinSession:
    user_id: int
    habits: list[Habit]
    current_index: int = 0
    results: list[CheckinResult] = field(default_factory=list)
    state: SessionState = SessionState.AWAITING_RESPONSE
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def start(cls, user_id: int, habits: list[Habit]) -> CheckinSession:
        return cls(user_id=user_id, habits=habits)

    def current_habit(self) -> Habit | None:
        if self.current_index < len(self.habits):
            return self.habits[self.current_index]
        return None

    def advance(self) -> Habit | None:
        self.current_index += 1
        if self.current_index >= len(self.habits):
            self.state = SessionState.DONE
            return None
        self.state = SessionState.AWAITING_RESPONSE
        return self.habits[self.current_index]

    def record_skip(self) -> None:
        habit = self.current_habit()
        if habit:
            self.results.append(
                CheckinResult(habit_name=habit.name.value, completed=False, skipped=True)
            )

    def record_completion(self, completion: Completion) -> None:
        habit = self.current_habit()
        if habit:
            self.results.append(
                CheckinResult(habit_name=habit.name.value, completed=True, skipped=False)
            )

    def is_complete(self) -> bool:
        return self.state == SessionState.DONE

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) - self.created_at > timedelta(hours=TTL_HOURS)

    def get_summary(self) -> CompletionSummary:
        total = len(self.results)
        completed = sum(1 for r in self.results if r.completed)
        return CompletionSummary(total=total, completed=completed)

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "current_index": self.current_index,
            "state": self.state.value,
            "created_at": self.created_at.isoformat(),
            "habits": [
                {
                    "id": h.id,
                    "user_id": h.user_id,
                    "name": h.name.value,
                    "description": h.description,
                    "frequency": h.frequency.value,
                    "verification_policy": h.verification_policy.value,
                    "is_active": h.is_active,
                    "created_at": h.created_at.isoformat(),
                }
                for h in self.habits
            ],
            "results": [
                {"habit_name": r.habit_name, "completed": r.completed, "skipped": r.skipped}
                for r in self.results
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> CheckinSession:
        habits = [
            Habit(
                id=h["id"],
                user_id=h["user_id"],
                name=HabitName(h["name"]),
                description=h["description"],
                frequency=Frequency(h["frequency"]),
                verification_policy=VerificationPolicy(h["verification_policy"]),
                is_active=h["is_active"],
                created_at=datetime.fromisoformat(h["created_at"]),
            )
            for h in data["habits"]
        ]
        results = [
            CheckinResult(
                habit_name=r["habit_name"],
                completed=r["completed"],
                skipped=r["skipped"],
            )
            for r in data["results"]
        ]
        return cls(
            user_id=data["user_id"],
            habits=habits,
            current_index=data["current_index"],
            results=results,
            state=SessionState(data["state"]),
            created_at=datetime.fromisoformat(data["created_at"]),
        )
```

- [ ] **Step 5: Run tests, verify green, commit**

Run: `uv run pytest tests/unit/ -v`
Expected: all PASS

```bash
git add src/habit_tracker/application/ tests/unit/test_checkin_session.py
git commit -m "feat: add application ports, DTOs, and CheckinSession state machine"
```

---

### Task 4: Application Use Cases

**Files:**
- Create: `src/habit_tracker/application/use_cases/__init__.py`
- Create: `src/habit_tracker/application/use_cases/register_user.py`
- Create: `src/habit_tracker/application/use_cases/create_habit.py`
- Create: `src/habit_tracker/application/use_cases/delete_habit.py`
- Create: `src/habit_tracker/application/use_cases/list_habits.py`
- Create: `src/habit_tracker/application/use_cases/start_checkin.py`
- Create: `src/habit_tracker/application/use_cases/verify_and_complete.py`
- Create: `tests/unit/conftest.py`
- Create: `tests/unit/test_register_user.py`
- Create: `tests/unit/test_create_habit.py`
- Create: `tests/unit/test_verify_and_complete.py`
- Create: `tests/unit/test_start_checkin.py`

**Interfaces:**
- Consumes: all domain entities/VOs from Tasks 1-2; all ports from Task 3
- Produces: `RegisterUser`, `CreateHabit`, `DeleteHabit`, `ListHabits`, `StartCheckin`, `VerifyAndComplete` use cases; `VerifyAndCompleteResult` DTO — used by handlers (Task 9)

- [ ] **Step 1: Create in-memory test fakes**

```python
# tests/unit/conftest.py
from __future__ import annotations

import dataclasses
from datetime import date, datetime, timezone

from habit_tracker.domain.entities.completion import Completion
from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.entities.user import User
from habit_tracker.domain.value_objects import HabitName, ProofType, TelegramId


class InMemoryUserRepository:
    def __init__(self) -> None:
        self._users: dict[int, User] = {}
        self._next_id = 1

    async def save(self, user: User) -> User:
        if user.id is None:
            user = dataclasses.replace(user, id=self._next_id)
            self._next_id += 1
        self._users[user.id] = user
        return user

    async def find_by_telegram_id(self, telegram_id: TelegramId) -> User | None:
        return next(
            (u for u in self._users.values() if u.telegram_id == telegram_id), None
        )


class InMemoryHabitRepository:
    def __init__(self) -> None:
        self._habits: dict[int, Habit] = {}
        self._next_id = 1

    async def save(self, habit: Habit) -> Habit:
        if habit.id is None:
            habit.id = self._next_id
            self._next_id += 1
        self._habits[habit.id] = habit
        return habit

    async def find_by_id(self, habit_id: int) -> Habit | None:
        return self._habits.get(habit_id)

    async def find_active_by_user(self, user_id: int) -> list[Habit]:
        return [h for h in self._habits.values() if h.user_id == user_id and h.is_active]

    async def find_by_user_and_name(self, user_id: int, name: HabitName) -> Habit | None:
        return next(
            (h for h in self._habits.values()
             if h.user_id == user_id and h.name == name and h.is_active),
            None,
        )

    async def delete(self, habit_id: int) -> None:
        self._habits.pop(habit_id, None)


class InMemoryCompletionRepository:
    def __init__(self) -> None:
        self._completions: dict[int, Completion] = {}
        self._next_id = 1

    async def save(self, completion: Completion) -> Completion:
        if completion.id is None:
            completion = dataclasses.replace(completion, id=self._next_id)
            self._next_id += 1
        self._completions[completion.id] = completion
        return completion

    async def find_today_by_habits(self, habit_ids: list[int]) -> list[Completion]:
        today = date.today()
        return [
            c for c in self._completions.values()
            if c.habit_id in habit_ids and c.completed_at.date() == today
        ]

    async def get_completion_dates(self, habit_id: int) -> list[date]:
        return sorted(
            {c.completed_at.date() for c in self._completions.values() if c.habit_id == habit_id},
            reverse=True,
        )

    async def find_by_habit_since(self, habit_id: int, since: date) -> list[Completion]:
        return [
            c for c in self._completions.values()
            if c.habit_id == habit_id and c.completed_at.date() >= since
        ]


class FakeProofVerifier:
    def __init__(self, result_verified: bool = True) -> None:
        self._result_verified = result_verified

    async def verify_text(self, habit, proof_text):
        from habit_tracker.domain.value_objects.proof_result import ProofResult
        return ProofResult(verified=self._result_verified, confidence=0.9, reasoning="test")

    async def verify_image(self, habit, image_bytes):
        from habit_tracker.domain.value_objects.proof_result import ProofResult
        return ProofResult(verified=self._result_verified, confidence=0.85, reasoning="test image")


class FakePatternAnalyzer:
    async def analyze_patterns(self, user_id, completions):
        return []

    async def generate_coaching_message(self, user_id, patterns, context):
        return "Keep going!"


class FakeMemoryStore:
    def __init__(self) -> None:
        self._insights: list[dict] = []

    async def store_insight(self, user_id: int, insight: str, category: str) -> None:
        self._insights.append({"user_id": user_id, "insight": insight, "category": category})

    async def get_insights(self, user_id: int):
        return []
```

- [ ] **Step 2: Implement RegisterUser and write tests**

```python
# src/habit_tracker/application/use_cases/register_user.py
from __future__ import annotations

from habit_tracker.application.ports.repositories import UserRepository
from habit_tracker.domain.entities.user import User
from habit_tracker.domain.value_objects.telegram_id import TelegramId


class RegisterUser:
    def __init__(self, user_repo: UserRepository) -> None:
        self._user_repo = user_repo

    async def execute(self, telegram_id: TelegramId, username: str | None = None) -> tuple[User, bool]:
        existing = await self._user_repo.find_by_telegram_id(telegram_id)
        if existing:
            return existing, False
        user = User.create(telegram_id, username)
        saved = await self._user_repo.save(user)
        return saved, True
```

```python
# tests/unit/test_register_user.py
import pytest

from habit_tracker.application.use_cases.register_user import RegisterUser
from habit_tracker.domain.value_objects import TelegramId
from tests.unit.conftest import InMemoryUserRepository


@pytest.fixture
def user_repo():
    return InMemoryUserRepository()


class TestRegisterUser:
    async def test_new_user(self, user_repo):
        uc = RegisterUser(user_repo)
        user, is_new = await uc.execute(TelegramId(123), "alice")
        assert is_new is True
        assert user.telegram_id == TelegramId(123)
        assert user.username == "alice"
        assert user.is_persisted()

    async def test_existing_user(self, user_repo):
        uc = RegisterUser(user_repo)
        await uc.execute(TelegramId(123), "alice")
        user, is_new = await uc.execute(TelegramId(123))
        assert is_new is False
        assert user.username == "alice"
```

- [ ] **Step 3: Implement CreateHabit, DeleteHabit, ListHabits and write tests**

```python
# src/habit_tracker/application/use_cases/create_habit.py
from __future__ import annotations

from habit_tracker.application.ports.repositories import HabitRepository, UserRepository
from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.exceptions import HabitAlreadyExistsError, UserNotFoundError
from habit_tracker.domain.value_objects.frequency import Frequency
from habit_tracker.domain.value_objects.habit_name import HabitName
from habit_tracker.domain.value_objects.telegram_id import TelegramId
from habit_tracker.domain.value_objects.verification_policy import VerificationPolicy


class CreateHabit:
    def __init__(self, user_repo: UserRepository, habit_repo: HabitRepository) -> None:
        self._user_repo = user_repo
        self._habit_repo = habit_repo

    async def execute(
        self,
        telegram_id: TelegramId,
        name: HabitName,
        description: str | None = None,
        frequency: Frequency = Frequency.DAILY,
        verification_policy: VerificationPolicy = VerificationPolicy.NONE,
    ) -> Habit:
        user = await self._user_repo.find_by_telegram_id(telegram_id)
        if not user:
            raise UserNotFoundError(f"User with telegram_id {telegram_id.value} not found")

        existing = await self._habit_repo.find_by_user_and_name(user.id, name)
        if existing:
            raise HabitAlreadyExistsError(f"Habit '{name.value}' already exists")

        habit = Habit.create(user.id, name, description, frequency, verification_policy)
        return await self._habit_repo.save(habit)
```

```python
# src/habit_tracker/application/use_cases/delete_habit.py
from __future__ import annotations

from habit_tracker.application.ports.repositories import HabitRepository, UserRepository
from habit_tracker.domain.exceptions import HabitNotFoundError, UserNotFoundError
from habit_tracker.domain.value_objects.habit_name import HabitName
from habit_tracker.domain.value_objects.telegram_id import TelegramId


class DeleteHabit:
    def __init__(self, user_repo: UserRepository, habit_repo: HabitRepository) -> None:
        self._user_repo = user_repo
        self._habit_repo = habit_repo

    async def execute(self, telegram_id: TelegramId, name: HabitName) -> None:
        user = await self._user_repo.find_by_telegram_id(telegram_id)
        if not user:
            raise UserNotFoundError(f"User with telegram_id {telegram_id.value} not found")

        habit = await self._habit_repo.find_by_user_and_name(user.id, name)
        if not habit:
            raise HabitNotFoundError(f"Habit '{name.value}' not found")

        habit.deactivate()
        await self._habit_repo.save(habit)
```

```python
# src/habit_tracker/application/use_cases/list_habits.py
from __future__ import annotations

from habit_tracker.application.ports.repositories import (
    CompletionRepository,
    HabitRepository,
    UserRepository,
)
from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.exceptions import UserNotFoundError
from habit_tracker.domain.value_objects.streak import Streak
from habit_tracker.domain.value_objects.telegram_id import TelegramId


class ListHabits:
    def __init__(
        self,
        user_repo: UserRepository,
        habit_repo: HabitRepository,
        completion_repo: CompletionRepository,
    ) -> None:
        self._user_repo = user_repo
        self._habit_repo = habit_repo
        self._completion_repo = completion_repo

    async def execute(self, telegram_id: TelegramId) -> list[tuple[Habit, Streak]]:
        user = await self._user_repo.find_by_telegram_id(telegram_id)
        if not user:
            raise UserNotFoundError(f"User with telegram_id {telegram_id.value} not found")

        habits = await self._habit_repo.find_active_by_user(user.id)
        results: list[tuple[Habit, Streak]] = []
        for habit in habits:
            dates = await self._completion_repo.get_completion_dates(habit.id)
            streak = Streak.from_dates(dates, habit.frequency)
            results.append((habit, streak))
        return results
```

```python
# tests/unit/test_create_habit.py
import pytest

from habit_tracker.application.use_cases.create_habit import CreateHabit
from habit_tracker.application.use_cases.register_user import RegisterUser
from habit_tracker.domain.exceptions import HabitAlreadyExistsError, UserNotFoundError
from habit_tracker.domain.value_objects import HabitName, TelegramId, VerificationPolicy
from tests.unit.conftest import InMemoryHabitRepository, InMemoryUserRepository


@pytest.fixture
def repos():
    return InMemoryUserRepository(), InMemoryHabitRepository()


class TestCreateHabit:
    async def test_creates_habit(self, repos):
        user_repo, habit_repo = repos
        await RegisterUser(user_repo).execute(TelegramId(1))
        habit = await CreateHabit(user_repo, habit_repo).execute(
            TelegramId(1), HabitName("gym")
        )
        assert habit.name == HabitName("gym")
        assert habit.is_persisted()

    async def test_user_not_found(self, repos):
        user_repo, habit_repo = repos
        with pytest.raises(UserNotFoundError):
            await CreateHabit(user_repo, habit_repo).execute(
                TelegramId(999), HabitName("gym")
            )

    async def test_duplicate_name(self, repos):
        user_repo, habit_repo = repos
        await RegisterUser(user_repo).execute(TelegramId(1))
        uc = CreateHabit(user_repo, habit_repo)
        await uc.execute(TelegramId(1), HabitName("gym"))
        with pytest.raises(HabitAlreadyExistsError):
            await uc.execute(TelegramId(1), HabitName("gym"))

    async def test_with_verification_policy(self, repos):
        user_repo, habit_repo = repos
        await RegisterUser(user_repo).execute(TelegramId(1))
        habit = await CreateHabit(user_repo, habit_repo).execute(
            TelegramId(1), HabitName("gym"), verification_policy=VerificationPolicy.PHOTO,
        )
        assert habit.verification_policy == VerificationPolicy.PHOTO
```

- [ ] **Step 4: Implement StartCheckin and VerifyAndComplete**

```python
# src/habit_tracker/application/use_cases/start_checkin.py
from __future__ import annotations

from datetime import date, timedelta

from habit_tracker.application.dtos.pattern_dto import CheckinContext
from habit_tracker.application.ports.ai_services import MemoryStore, PatternAnalyzer
from habit_tracker.application.ports.repositories import (
    CompletionRepository,
    HabitRepository,
    UserRepository,
)
from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.exceptions import UserNotFoundError
from habit_tracker.domain.value_objects.telegram_id import TelegramId


class StartCheckin:
    def __init__(
        self,
        user_repo: UserRepository,
        habit_repo: HabitRepository,
        completion_repo: CompletionRepository,
        pattern_analyzer: PatternAnalyzer,
        memory_store: MemoryStore,
    ) -> None:
        self._user_repo = user_repo
        self._habit_repo = habit_repo
        self._completion_repo = completion_repo
        self._pattern_analyzer = pattern_analyzer
        self._memory_store = memory_store

    async def execute(self, telegram_id: TelegramId) -> tuple[list[Habit], str]:
        user = await self._user_repo.find_by_telegram_id(telegram_id)
        if not user:
            raise UserNotFoundError(f"User with telegram_id {telegram_id.value} not found")

        habits = await self._habit_repo.find_active_by_user(user.id)
        if not habits:
            return [], "No active habits. Create one with /add_habit!"

        habit_ids = [h.id for h in habits]
        today_completions = await self._completion_repo.find_today_by_habits(habit_ids)
        completed_ids = {c.habit_id for c in today_completions}
        pending = [h for h in habits if h.id not in completed_ids]

        if not pending:
            return [], "All habits completed for today! Great job!"

        completions_by_habit: dict[str, list] = {}
        since = date.today() - timedelta(days=30)
        for habit in habits:
            comps = await self._completion_repo.find_by_habit_since(habit.id, since)
            completions_by_habit[habit.name.value] = comps

        patterns = await self._pattern_analyzer.analyze_patterns(user.id, completions_by_habit)
        context = CheckinContext(habits=pending, today_completions=today_completions, patterns=patterns)
        coaching = await self._pattern_analyzer.generate_coaching_message(user.id, patterns, context)

        return pending, coaching
```

```python
# src/habit_tracker/application/use_cases/verify_and_complete.py
from __future__ import annotations

from dataclasses import dataclass

from habit_tracker.application.ports.ai_services import ProofVerifier
from habit_tracker.application.ports.repositories import CompletionRepository
from habit_tracker.domain.entities.completion import Completion
from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.exceptions import InvalidProofTypeError
from habit_tracker.domain.value_objects.proof_result import ProofResult
from habit_tracker.domain.value_objects.streak import Streak
from habit_tracker.domain.value_objects.verification_policy import ProofType, VerificationPolicy


@dataclass(frozen=True)
class VerifyAndCompleteResult:
    completion: Completion | None
    proof_result: ProofResult | None
    streak: Streak | None

    @property
    def verified(self) -> bool:
        if self.proof_result is None:
            return self.completion is not None
        return self.proof_result.verified


class VerifyAndComplete:
    def __init__(
        self,
        completion_repo: CompletionRepository,
        proof_verifier: ProofVerifier,
    ) -> None:
        self._completion_repo = completion_repo
        self._proof_verifier = proof_verifier

    async def execute(
        self,
        habit: Habit,
        proof_text: str | None = None,
        image_bytes: bytes | None = None,
    ) -> VerifyAndCompleteResult:
        if habit.verification_policy == VerificationPolicy.NONE:
            completion = Completion.create(habit.id, ProofType.NONE, verified=True)
            saved = await self._completion_repo.save(completion)
            dates = await self._completion_repo.get_completion_dates(habit.id)
            streak = Streak.from_dates(dates, habit.frequency)
            return VerifyAndCompleteResult(completion=saved, proof_result=None, streak=streak)

        if habit.verification_policy == VerificationPolicy.TEXT:
            if not proof_text:
                raise InvalidProofTypeError("Text proof required for this habit")
            result = await self._proof_verifier.verify_text(habit, proof_text)
            proof_type = ProofType.TEXT

        elif habit.verification_policy == VerificationPolicy.PHOTO:
            if not image_bytes:
                raise InvalidProofTypeError("Photo proof required for this habit")
            result = await self._proof_verifier.verify_image(habit, image_bytes)
            proof_type = ProofType.PHOTO

        else:
            raise InvalidProofTypeError(f"Unknown policy: {habit.verification_policy}")

        if not result.verified:
            return VerifyAndCompleteResult(completion=None, proof_result=result, streak=None)

        completion = Completion.create(
            habit.id, proof_type, verified=True, verification_notes=result.reasoning
        )
        saved = await self._completion_repo.save(completion)
        dates = await self._completion_repo.get_completion_dates(habit.id)
        streak = Streak.from_dates(dates, habit.frequency)
        return VerifyAndCompleteResult(completion=saved, proof_result=result, streak=streak)
```

```python
# src/habit_tracker/application/use_cases/__init__.py
```

- [ ] **Step 5: Write tests for VerifyAndComplete and StartCheckin**

```python
# tests/unit/test_verify_and_complete.py
import pytest

from habit_tracker.application.use_cases.verify_and_complete import VerifyAndComplete
from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.exceptions import InvalidProofTypeError
from habit_tracker.domain.value_objects import HabitName, VerificationPolicy
from tests.unit.conftest import FakeProofVerifier, InMemoryCompletionRepository


def _habit(policy: VerificationPolicy, habit_id: int = 1) -> Habit:
    h = Habit.create(user_id=1, name=HabitName("test"), verification_policy=policy)
    h.id = habit_id
    return h


@pytest.fixture
def completion_repo():
    return InMemoryCompletionRepository()


class TestVerifyAndComplete:
    async def test_none_policy_auto_completes(self, completion_repo):
        uc = VerifyAndComplete(completion_repo, FakeProofVerifier())
        result = await uc.execute(_habit(VerificationPolicy.NONE))
        assert result.verified is True
        assert result.completion is not None
        assert result.proof_result is None
        assert result.streak is not None

    async def test_text_verified(self, completion_repo):
        uc = VerifyAndComplete(completion_repo, FakeProofVerifier(result_verified=True))
        result = await uc.execute(_habit(VerificationPolicy.TEXT), proof_text="I ran 5km")
        assert result.verified is True
        assert result.completion is not None

    async def test_text_rejected(self, completion_repo):
        uc = VerifyAndComplete(completion_repo, FakeProofVerifier(result_verified=False))
        result = await uc.execute(_habit(VerificationPolicy.TEXT), proof_text="maybe")
        assert result.verified is False
        assert result.completion is None
        assert result.proof_result is not None

    async def test_photo_verified(self, completion_repo):
        uc = VerifyAndComplete(completion_repo, FakeProofVerifier(result_verified=True))
        result = await uc.execute(_habit(VerificationPolicy.PHOTO), image_bytes=b"fake-image")
        assert result.verified is True

    async def test_text_required_but_missing(self, completion_repo):
        uc = VerifyAndComplete(completion_repo, FakeProofVerifier())
        with pytest.raises(InvalidProofTypeError):
            await uc.execute(_habit(VerificationPolicy.TEXT))

    async def test_photo_required_but_missing(self, completion_repo):
        uc = VerifyAndComplete(completion_repo, FakeProofVerifier())
        with pytest.raises(InvalidProofTypeError):
            await uc.execute(_habit(VerificationPolicy.PHOTO))
```

```python
# tests/unit/test_start_checkin.py
import pytest

from habit_tracker.application.use_cases.register_user import RegisterUser
from habit_tracker.application.use_cases.create_habit import CreateHabit
from habit_tracker.application.use_cases.start_checkin import StartCheckin
from habit_tracker.domain.exceptions import UserNotFoundError
from habit_tracker.domain.value_objects import HabitName, TelegramId
from tests.unit.conftest import (
    FakeMemoryStore,
    FakePatternAnalyzer,
    InMemoryCompletionRepository,
    InMemoryHabitRepository,
    InMemoryUserRepository,
)


@pytest.fixture
def deps():
    return (
        InMemoryUserRepository(),
        InMemoryHabitRepository(),
        InMemoryCompletionRepository(),
        FakePatternAnalyzer(),
        FakeMemoryStore(),
    )


class TestStartCheckin:
    async def test_returns_pending_habits(self, deps):
        user_repo, habit_repo, comp_repo, analyzer, memory = deps
        await RegisterUser(user_repo).execute(TelegramId(1))
        await CreateHabit(user_repo, habit_repo).execute(TelegramId(1), HabitName("gym"))
        await CreateHabit(user_repo, habit_repo).execute(TelegramId(1), HabitName("read"))

        uc = StartCheckin(user_repo, habit_repo, comp_repo, analyzer, memory)
        pending, coaching = await uc.execute(TelegramId(1))

        assert len(pending) == 2
        assert coaching == "Keep going!"

    async def test_no_habits(self, deps):
        user_repo, habit_repo, comp_repo, analyzer, memory = deps
        await RegisterUser(user_repo).execute(TelegramId(1))

        uc = StartCheckin(user_repo, habit_repo, comp_repo, analyzer, memory)
        pending, msg = await uc.execute(TelegramId(1))

        assert len(pending) == 0
        assert "add_habit" in msg.lower()

    async def test_user_not_found(self, deps):
        user_repo, habit_repo, comp_repo, analyzer, memory = deps
        uc = StartCheckin(user_repo, habit_repo, comp_repo, analyzer, memory)
        with pytest.raises(UserNotFoundError):
            await uc.execute(TelegramId(999))
```

- [ ] **Step 6: Run all unit tests, verify green, commit**

Run: `uv run pytest tests/unit/ -v`
Expected: all PASS

```bash
git add src/habit_tracker/application/use_cases/ tests/unit/
git commit -m "feat: add use cases — RegisterUser, CreateHabit, DeleteHabit, ListHabits, StartCheckin, VerifyAndComplete"
```

---

### Task 5: Config & Database

**Files:**
- Create: `src/habit_tracker/infrastructure/__init__.py`
- Create: `src/habit_tracker/infrastructure/config/__init__.py`
- Create: `src/habit_tracker/infrastructure/config/settings.py`
- Create: `src/habit_tracker/infrastructure/logging/__init__.py`
- Create: `src/habit_tracker/infrastructure/logging/logger.py`
- Create: `src/habit_tracker/infrastructure/database/__init__.py`
- Create: `src/habit_tracker/infrastructure/database/connection.py`
- Create: `src/habit_tracker/infrastructure/database/models.py`
- Create: `src/habit_tracker/infrastructure/database/repositories/__init__.py`
- Create: `src/habit_tracker/infrastructure/database/repositories/user_repository.py`
- Create: `src/habit_tracker/infrastructure/database/repositories/habit_repository.py`
- Create: `src/habit_tracker/infrastructure/database/repositories/completion_repository.py`
- Create: `tests/integration/conftest.py`
- Create: `tests/integration/test_repositories.py`

**Interfaces:**
- Consumes: domain entities/VOs (Tasks 1-2), repository Protocols (Task 3)
- Produces: `Settings`, `DatabaseSessionManager`, `Base` (ORM base), `UserModel`/`HabitModel`/`CompletionModel`, `SQLAlchemyUserRepository`/`SQLAlchemyHabitRepository`/`SQLAlchemyCompletionRepository` — used by composition root (Task 9) and integration tests

- [ ] **Step 1: Implement Settings and logger**

Settings class with `__init__`-based env var loading. See spec section "Config" for exact fields. `get_mem0_config()` parses `DATABASE_URL` into mem0's dict format using `urllib.parse.urlparse`.

Logger: configure `structlog` with JSON rendering, bound to Python's `logging` module.

- [ ] **Step 2: Implement database connection and ORM models**

`DatabaseSessionManager`: async engine via asyncpg, `DeclarativeBase` (SQLAlchemy 2.0), configurable pool. SSL connect_args for Azure.

ORM models:
- `UserModel`: `id` (Integer PK), `telegram_id` (BigInteger, unique, indexed), `username` (String 255), `created_at` (DateTime TZ)
- `HabitModel`: `id` (Integer PK), `user_id` (FK → users, CASCADE), `name` (String 255), `description` (Text), `frequency` (String 50), `verification_policy` (String 50), `is_active` (Boolean, default True), `created_at` (DateTime TZ). Composite index on `(user_id, is_active)`.
- `CompletionModel`: `id` (Integer PK), `habit_id` (FK → habits, CASCADE), `completed_at` (DateTime TZ), `proof_type` (String 50), `verified` (Boolean), `verification_notes` (Text). Composite index on `(habit_id, completed_at)`. No `missed` column.

- [ ] **Step 3: Implement SQLAlchemy repositories**

Each repository maps between ORM models and domain entities. Key methods:
- `save()`: create (INSERT) if `entity.id is None`, else UPDATE
- `find_*()`: query + `_to_entity()` conversion
- `CompletionRepository.find_today_by_habits(habit_ids)`: `WHERE habit_id IN (:ids) AND completed_at >= today`
- `CompletionRepository.get_completion_dates(habit_id)`: returns `list[date]` via `SELECT DISTINCT DATE(completed_at)`

- [ ] **Step 4: Write integration tests with testcontainers**

```python
# tests/integration/conftest.py
from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import pytest
import pytest_asyncio
import vcr as vcrpy
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from testcontainers.postgres import PostgresContainer
from vcr import VCR

from habit_tracker.infrastructure.database.models import Base


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    with PostgresContainer("pgvector/pgvector:pg17") as container:
        container.start()
        yield container


@pytest_asyncio.fixture
async def test_engine(postgres_container: PostgresContainer) -> AsyncGenerator[AsyncEngine, None]:
    url = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2", "postgresql+asyncpg"
    )
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.commit()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def test_session(test_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    async_session = sessionmaker(
        bind=test_engine, class_=AsyncSession,
        expire_on_commit=False, autoflush=False, autocommit=False,
    )
    async with async_session() as session:
        yield session
        await session.rollback()


@pytest.fixture(scope="module")
def vcr_config() -> VCR:
    cassette_dir = Path(__file__).parent / "cassettes"
    cassette_dir.mkdir(exist_ok=True)
    return vcrpy.VCR(
        cassette_library_dir=str(cassette_dir),
        filter_headers=["authorization", "api-key"],
        ignore_hosts=["localhost", "unix", "docker"],
        record_mode="once",
        match_on=["uri", "body"],
    )
```

Integration tests verify: save + find roundtrip for each repo, `find_today_by_habits` filters correctly, `get_completion_dates` returns deduplicated sorted dates, composite indexes exist.

- [ ] **Step 5: Run integration tests, verify green, commit**

Run: `uv run pytest tests/integration/test_repositories.py -v` (requires Docker)
Expected: PASS

```bash
git add src/habit_tracker/infrastructure/ tests/integration/
git commit -m "feat: add settings, database connection, ORM models, SQLAlchemy repositories"
```

---

### Task 6: LLM Client & Proof Verifier

**Files:**
- Create: `src/habit_tracker/infrastructure/ai/__init__.py`
- Create: `src/habit_tracker/infrastructure/ai/llm_client.py`
- Create: `src/habit_tracker/infrastructure/ai/proof_verifier.py`
- Create: `tests/integration/test_proof_verifier.py`

**Interfaces:**
- Consumes: `ProofVerifier` protocol (Task 3), `Habit` entity (Task 2), `ProofResult` VO (Task 1)
- Produces: `LiteLLMClient`, `LiteLLMProofVerifier` — used by composition root (Task 9)

- [ ] **Step 1: Implement LiteLLM client wrapper**

`LiteLLMClient` wraps `litellm.acompletion`. Two methods:
- `complete(messages, model, temperature) -> str` — plain text completion
- `complete_with_schema(messages, schema, model, temperature) -> dict` — JSON response parsed into dict

Uses `response_format={"type": "json_object"}` with the schema injected into the system message.

- [ ] **Step 2: Implement LiteLLMProofVerifier**

Implements `ProofVerifier` protocol. Uses `LiteLLMClient` for:
- `verify_text(habit, proof_text)` — system prompt describes the habit, asks LLM to evaluate the text proof. Returns `ProofResult`.
- `verify_image(habit, image_bytes)` — base64-encodes image, sends as vision content. Returns `ProofResult`.

One-shot verification per the design — no multi-stage quiz.

- [ ] **Step 3: Write integration tests with VCR cassettes**

Tests use VCR to record/replay LiteLLM HTTP calls. Test text verification (accepted and rejected) and image verification. First run with `record_mode="once"` creates cassettes; CI replays them.

- [ ] **Step 4: Run tests, commit**

```bash
git add src/habit_tracker/infrastructure/ai/ tests/integration/test_proof_verifier.py
git commit -m "feat: add LiteLLM client and proof verifier"
```

---

### Task 7: Memory Store & Pattern Analyzer

**Files:**
- Create: `src/habit_tracker/infrastructure/memory/__init__.py`
- Create: `src/habit_tracker/infrastructure/memory/mem0_store.py`
- Create: `src/habit_tracker/infrastructure/ai/pattern_analyzer.py`
- Create: `tests/integration/test_mem0_store.py`
- Create: `tests/integration/test_pattern_analyzer.py`

**Interfaces:**
- Consumes: `MemoryStore` protocol, `PatternAnalyzer` protocol (Task 3), `LiteLLMClient` (Task 6)
- Produces: `Mem0MemoryStore`, `LLMPatternAnalyzer` — used by composition root (Task 9)

- [ ] **Step 1: Implement Mem0MemoryStore**

Wraps `mem0.AsyncMemory`. Constructor takes the config dict from `Settings.get_mem0_config()`. Methods:
- `store_insight(user_id, insight, category)` — calls `mem0.add()` with metadata
- `get_insights(user_id)` — calls `mem0.search()` and maps to `MemoryInsight` DTOs

Proper error handling: catch mem0 exceptions, log with structlog, don't crash the bot.

- [ ] **Step 2: Implement LLMPatternAnalyzer**

`analyze_patterns(user_id, completions)` — pure Python analysis on completion data:
- Day-of-week frequency counting per habit
- Detect if a habit is consistently skipped on certain days (>70% skip rate)
- Compute completion rate trends over 4-week rolling windows

`generate_coaching_message(user_id, patterns, context)` — single LLM call:
- System prompt: "You are a supportive habit coach. Generate a short, personal message."
- Includes: computed patterns as structured text, any mem0 insights for the user, list of today's pending habits
- Returns the coaching message string

- [ ] **Step 3: Write integration tests**

`test_mem0_store.py`: testcontainers for Postgres + VCR for embedding API calls. Tests store and retrieve roundtrip.
`test_pattern_analyzer.py`: VCR for the LLM coaching call. Tests pattern analysis with sample completion data.

- [ ] **Step 4: Run tests, commit**

```bash
git add src/habit_tracker/infrastructure/memory/ src/habit_tracker/infrastructure/ai/pattern_analyzer.py tests/integration/test_mem0_store.py tests/integration/test_pattern_analyzer.py
git commit -m "feat: add mem0 memory store and pattern analyzer"
```

---

### Task 8: Observability & Bot Persistence

**Files:**
- Create: `src/habit_tracker/infrastructure/observability/__init__.py`
- Create: `src/habit_tracker/infrastructure/observability/tracing.py`
- Create: `src/habit_tracker/infrastructure/persistence/__init__.py`
- Create: `src/habit_tracker/infrastructure/persistence/postgres_persistence.py`
- Create: `tests/integration/test_postgres_persistence.py`

**Interfaces:**
- Consumes: `DatabaseSessionManager` (Task 5), `CheckinSession` (Task 3)
- Produces: `setup_tracing()`, `trace_handler()`, `trace_operation()`, `PostgresPersistence` — used by composition root (Task 9)

- [ ] **Step 1: Implement Arize Phoenix tracing**

`setup_tracing(collector_endpoint)`:
- Register Phoenix OTEL tracer provider
- Instrument LiteLLM via `openinference-instrumentation-litellm`
- Support optional `PHOENIX_API_KEY` for authenticated endpoints

`@trace_handler(name)` decorator: creates root span with user attributes.
`@trace_operation(name, op_type)` decorator: creates child span for use cases/repos.

Both decorators are no-ops when tracing is disabled.

- [ ] **Step 2: Implement PostgresPersistence**

Extends python-telegram-bot's `BasePersistence`. Uses a `bot_persistence` table (key TEXT PK, data JSONB, updated_at TIMESTAMP). Methods:
- `get_user_data()` / `update_user_data()` — load/store `user_data` dict
- `get_chat_data()` / `update_chat_data()` — load/store `chat_data` dict
- `get_bot_data()` / `update_bot_data()` — load/store `bot_data` dict
- `get_callback_data()` / `update_callback_data()` — no-op (not used)
- `get_conversations()` / `update_conversation()` — no-op (not used)

Uses raw asyncpg queries (not SQLAlchemy) against the same `DATABASE_URL` to avoid session conflicts with the bot's event loop.

- [ ] **Step 3: Write integration test for persistence roundtrip**

Test stores a `CheckinSession` via `to_dict()` in `user_data`, retrieves it, and verifies `from_dict()` restores the session correctly. Uses testcontainers.

- [ ] **Step 4: Run tests, commit**

```bash
git add src/habit_tracker/infrastructure/observability/ src/habit_tracker/infrastructure/persistence/ tests/integration/test_postgres_persistence.py
git commit -m "feat: add Phoenix tracing and PostgreSQL bot persistence"
```

---

### Task 9: Presentation Layer

**Files:**
- Create: `src/habit_tracker/presentation/__init__.py`
- Create: `src/habit_tracker/presentation/formatters.py`
- Create: `src/habit_tracker/presentation/handlers/__init__.py`
- Create: `src/habit_tracker/presentation/handlers/command_handlers.py`
- Create: `src/habit_tracker/presentation/handlers/checkin_handlers.py`
- Create: `src/habit_tracker/presentation/handlers/proof_handlers.py`
- Create: `src/habit_tracker/presentation/main.py`
- Create: `tests/unit/test_formatters.py`

**Interfaces:**
- Consumes: all use cases (Task 4), `CheckinSession` (Task 3), all infrastructure adapters (Tasks 5-8), `Settings` (Task 5), formatters, tracing decorators
- Produces: the complete running Telegram bot application

- [ ] **Step 1: Implement formatters and write tests**

```python
# tests/unit/test_formatters.py
from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.value_objects import HabitName, VerificationPolicy
from habit_tracker.domain.value_objects.completion_summary import CompletionSummary
from habit_tracker.domain.value_objects.streak import Streak
from habit_tracker.presentation.formatters import (
    format_checkin_prompt,
    format_checkin_summary,
    format_habit_list,
    format_help,
)


class TestFormatters:
    def test_format_help_contains_commands(self):
        text = format_help()
        assert "/start" in text
        assert "/add_habit" in text
        assert "/checkin" in text

    def test_format_habit_list_empty(self):
        text = format_habit_list([], [])
        assert "no active habits" in text.lower()

    def test_format_habit_list_with_streak(self):
        h = Habit.create(user_id=1, name=HabitName("gym"))
        h.id = 1
        s = Streak(current=5, longest=10, is_active=True)
        text = format_habit_list([h], [s])
        assert "gym" in text
        assert "5" in text

    def test_format_checkin_prompt(self):
        h = Habit.create(user_id=1, name=HabitName("read"), verification_policy=VerificationPolicy.TEXT)
        text = format_checkin_prompt(h)
        assert "read" in text.lower()

    def test_format_summary(self):
        s = CompletionSummary(total=3, completed=2)
        text = format_checkin_summary(s)
        assert "2" in text
        assert "3" in text
```

Formatters: pure functions returning Telegram-formatted strings (Markdown). Each is 5-15 lines.

- [ ] **Step 2: Implement command handlers**

Thin handlers — each: extract args from `update.message.text`, call use case, format response, send. Wrapped with `@trace_handler`. Handle domain exceptions by sending error messages to user.

- [ ] **Step 3: Implement checkin and proof handlers**

`checkin_handlers.py`: `/checkin` creates `CheckinSession`, calls `StartCheckin`, stores session in `context.user_data["checkin_session"]`, sends coaching message + first habit prompt.

`proof_handlers.py`: text message handler and photo handler. Read `CheckinSession` from `context.user_data`. Route based on `session.state`:
- `AWAITING_RESPONSE`: parse yes/no/skip
- `AWAITING_PROOF`: call `VerifyAndComplete` with text
- Photo: call `VerifyAndComplete` with image bytes

After each habit: call `session.advance()`. If `session.is_complete()`: show summary, clear session. Else: send next habit prompt.

Store memory insight after completed check-in.

- [ ] **Step 4: Implement main.py — composition root**

Wires all dependencies. Uses `ApplicationBuilder` with webhook config. Registers handlers in order:
1. CommandHandler for `/start`, `/add_habit`, `/list_habits`, `/delete_habit`, `/help`, `/checkin`
2. MessageHandler for photos (during checkin)
3. MessageHandler for text (during checkin, non-command)

Use case factories create fresh DB sessions per request. Handlers receive the factories via `application.bot_data`.

`async_main()`: validates settings, sets up tracing if enabled, starts webhook.

- [ ] **Step 5: Run formatter tests, commit**

Run: `uv run pytest tests/unit/test_formatters.py -v`

```bash
git add src/habit_tracker/presentation/ tests/unit/test_formatters.py
git commit -m "feat: add presentation layer — handlers, formatters, composition root"
```

---

### Task 10: Migration, Deployment & CI/CD

**Files:**
- Modify: `alembic/env.py`
- Replace: `alembic/versions/` (new initial migration)
- Modify: `Dockerfile`
- Modify: `scripts/startup.sh`
- Remove: `scripts/health_server.py`
- Modify: `scripts/deploy.sh`
- Modify: `infra/modules/web-app/main.tf` (env vars, webhook URL)
- Modify: `infra/modules/web-app/variables.tf`
- Modify: `infra/live/web-app/terragrunt.hcl`
- Modify: `.env.example`
- Modify: `.env.azure.example`
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: ORM `Base` from Task 5, all infrastructure from Tasks 5-8
- Produces: deployable Docker image, CI pipeline, updated infra

- [ ] **Step 1: Create new Alembic migration**

Replace the existing migration with a new initial one matching the new schema (no `missed` column, added `verification_policy`, added `bot_persistence` table, composite indexes).

Update `alembic/env.py` to import `Base` from the new models location.

- [ ] **Step 2: Update Dockerfile**

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY alembic/ alembic/
COPY alembic.ini .
RUN uv sync --frozen --no-dev

FROM python:3.13-slim-bookworm
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini .
COPY scripts/startup.sh scripts/startup.sh
RUN chmod +x scripts/startup.sh
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8443
ENTRYPOINT ["/app/scripts/startup.sh"]
```

- [ ] **Step 3: Simplify startup.sh**

Remove `health_server.py` launch. Remove conflicting env var defaults. Just verify required vars and exec the bot:

```bash
#!/bin/bash
set -e
for var in TELEGRAM_BOT_TOKEN DATABASE_URL WEBHOOK_URL; do
    if [ -z "${!var}" ]; then echo "ERROR: $var not set" && exit 1; fi
done
# Run migrations
alembic upgrade head
exec python -m habit_tracker
```

- [ ] **Step 4: Update Terragrunt web-app module**

Add `WEBHOOK_URL` and `WEBHOOK_SECRET` to app settings. Remove `MEMORY_PG_*` env vars. Add `WEBSITES_PORT=8443` for webhook. Add code comments noting F1 limitations and production recommendations.

- [ ] **Step 5: Update .env.example files**

```
# .env.example
TELEGRAM_BOT_TOKEN=your-token
OPENAI_API_KEY=your-key
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/habit_tracker
LLM_MODEL=gpt-4o-mini
LLM_TEMPERATURE=0.7
COLLECTOR_ENDPOINT=http://localhost:4317
ENABLE_TRACING=true
WEBHOOK_URL=https://your-domain.com/webhook
WEBHOOK_SECRET=your-secret
```

- [ ] **Step 6: Create GitHub Actions CI workflow**

```yaml
# .github/workflows/ci.yml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --frozen
      - run: uv run pytest tests/unit/ -v --tb=short

  integration:
    needs: unit
    runs-on: ubuntu-latest
    services:
      docker:
        image: docker:dind
        options: --privileged
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --frozen
      - run: uv run pytest tests/integration/ -v --tb=short
        env:
          VCR_RECORD_MODE: none

  deploy:
    needs: integration
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: azure/login@v2
        with:
          creds: ${{ secrets.AZURE_CREDENTIALS }}
      - run: |
          ACR_NAME=$(az acr list -g ${{ vars.AZURE_RESOURCE_GROUP }} --query '[0].name' -o tsv)
          az acr login --name $ACR_NAME
          docker build -t $ACR_NAME.azurecr.io/habit-tracker:${{ github.sha }} .
          docker push $ACR_NAME.azurecr.io/habit-tracker:${{ github.sha }}
          WEBAPP=$(az webapp list -g ${{ vars.AZURE_RESOURCE_GROUP }} --query '[0].name' -o tsv)
          az webapp restart -n $WEBAPP -g ${{ vars.AZURE_RESOURCE_GROUP }}
```

- [ ] **Step 7: Run full test suite, commit**

```bash
uv run pytest tests/unit/ -v
uv run pytest tests/integration/ -v  # requires Docker
git add -A
git commit -m "feat: add migration, Dockerfile, CI/CD, deployment updates"
```

---

## Summary

| Task | Deliverable | Tests |
|------|------------|-------|
| 1 | Domain value objects + exceptions | unit: VOs, Streak, CompletionSummary |
| 2 | Domain entities (User, Habit, Completion) | unit: Habit behavior |
| 3 | Application ports, DTOs, CheckinSession | unit: session state machine |
| 4 | All 6 use cases | unit: with in-memory fakes |
| 5 | Settings, DB connection, ORM models, repositories | integration: testcontainers |
| 6 | LiteLLM client, proof verifier | integration: VCR cassettes |
| 7 | mem0 store, pattern analyzer | integration: testcontainers + VCR |
| 8 | Phoenix tracing, bot persistence | integration: testcontainers |
| 9 | Handlers, formatters, composition root | unit: formatters |
| 10 | Migration, Dockerfile, CI/CD | full suite green |
