# AI Habit Tracker — Full Rebuild Design Spec

## Overview

Telegram-based habit tracker with AI-powered proof verification and personalized coaching. Users create habits with configurable verification policies, do daily check-ins where they prove completions, and receive behavioral-pattern-based coaching from an agent that remembers them over time.

Built as a reference project for a multi-part newsletter tutorial series (Neural Maze / Decoding ML style). Code must be exemplary Clean Architecture in Python.

## Tech Stack

- **Python 3.13**, **uv** for package management
- **python-telegram-bot** with webhooks (not polling)
- **SQLAlchemy 2.0** async + **asyncpg** + **PostgreSQL 17** + **pgvector**
- **LiteLLM** for provider-agnostic LLM access
- **mem0** for user memory (backed by the same PostgreSQL + pgvector)
- **Arize Phoenix** for observability/tracing via OTEL
- **Terragrunt + OpenTofu** for Azure infrastructure
- **GitHub Actions** for CI/CD

## Architecture: Classical Layered Clean Architecture

```
src/habit_tracker/
  domain/           → entities, value objects, exceptions, domain services
  application/      → use cases, ports (protocols), DTOs, checkin session
  infrastructure/   → adapters: database, LLM, memory, tracing, config, persistence
  presentation/     → telegram handlers (thin), response formatters
```

Dependency rule: domain ← application ← infrastructure/presentation. Inner layers never import outer layers. Application defines Protocol interfaces (ports); infrastructure provides implementations (adapters).

---

## Domain Layer

### Entities

**User**
- `id: int | None`, `telegram_id: TelegramId`, `username: str | None`, `created_at: datetime`
- Factory: `User.create(telegram_id, username)`
- `is_persisted() -> bool`

**Habit**
- `id: int | None`, `user_id: int`, `name: HabitName`, `description: str | None`, `frequency: Frequency`, `verification_policy: VerificationPolicy`, `is_active: bool`, `created_at: datetime`
- Factory: `Habit.create(user_id, name, description, frequency, verification_policy)`
- `deactivate()` — soft delete
- `requires_proof() -> bool` — True if policy is TEXT or PHOTO
- `accepts_proof_type(proof_type: ProofType) -> bool` — validates proof matches policy

**Completion**
- `id: int | None`, `habit_id: int`, `completed_at: datetime`, `proof_type: ProofType`, `verified: bool`, `verification_notes: str | None`
- Factory: `Completion.create(habit_id, proof_type, verified, verification_notes)`
- No `missed` field. Missed days are computed as gaps, never stored.

### Value Objects (frozen dataclasses)

- **TelegramId** — wraps `int`, validates positive
- **HabitName** — wraps `str`, validates non-empty, max 100 chars
- **Frequency** — enum: `DAILY`, `WEEKLY`
- **VerificationPolicy** — enum: `NONE` (yes/no only), `TEXT` (describe what you did, LLM checks), `PHOTO` (send image, vision LLM checks)
- **ProofType** — enum: `NONE`, `TEXT`, `PHOTO`
- **ProofResult** — `verified: bool`, `confidence: float`, `reasoning: str`
- **Streak** — computed from a list of completion dates. Properties: `current_days: int`, `longest_days: int`, `is_active: bool`. Pure domain logic, not stored. Class method `Streak.from_dates(dates: list[date], frequency: Frequency) -> Streak`.
- **CompletionSummary** — `total: int`, `completed: int`. Properties: `pending: int`, `completion_rate: float`. Methods: `get_encouragement() -> str`. Computed on-the-fly from real completions for a given day.

### Domain Exceptions

- `HabitTrackerError` (base)
- `UserNotFoundError`
- `HabitNotFoundError`
- `HabitAlreadyExistsError`
- `HabitLimitExceededError`
- `InvalidProofTypeError`

---

## Application Layer

### Ports (Protocols)

**Repositories:**

```python
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
    async def find_today_by_user(self, user_id: int) -> list[Completion]: ...
    async def get_completion_dates(self, habit_id: int) -> list[date]: ...
    async def find_by_habit_since(self, habit_id: int, since: date) -> list[Completion]: ...
```

**AI Services:**

```python
class ProofVerifier(Protocol):
    async def verify_text(self, habit: Habit, proof_text: str) -> ProofResult: ...
    async def verify_image(self, habit: Habit, image_bytes: bytes) -> ProofResult: ...

class MemoryStore(Protocol):
    async def store_insight(self, user_id: int, insight: str, category: str) -> None: ...
    async def get_insights(self, user_id: int) -> list[MemoryInsight]: ...

class PatternAnalyzer(Protocol):
    async def analyze_patterns(self, user_id: int, completions: dict[str, list[Completion]]) -> list[BehavioralPattern]: ...
    async def generate_coaching_message(self, user_id: int, patterns: list[BehavioralPattern], context: CheckinContext) -> str: ...
```

### DTOs

- **HabitDTO** — `id`, `name`, `description`, `frequency`, `verification_policy`, `is_active`
- **CompletionDTO** — `id`, `habit_id`, `completed_at`, `proof_type`, `verified`
- **MemoryInsight** — `content: str`, `category: str`, `created_at: datetime`
- **BehavioralPattern** — `pattern_type: str`, `description: str`, `habit_name: str | None`, `confidence: float`
- **CheckinContext** — `habits: list[Habit]`, `today_completions: list[Completion]`, `patterns: list[BehavioralPattern]`

### Use Cases

**RegisterUser** — finds existing user by telegram_id or creates new one. Returns `(user, is_new)`.

**CreateHabit** — validates user exists, name non-empty, no duplicate active habit with same name. Takes `verification_policy` parameter (defaults to `NONE`). Returns created habit.

**DeleteHabit** — finds habit by user + name, calls `habit.deactivate()`, saves. Raises `HabitNotFoundError` if not found.

**ListHabits** — returns active habits with streak info. For each habit, fetches completion dates and computes `Streak.from_dates()`.

**StartCheckin** — the entry point for daily check-in:
1. Fetch active habits for user
2. Find today's completions, determine which habits are still pending
3. Fetch completion history, compute behavioral patterns via `PatternAnalyzer`
4. Generate personalized coaching message using patterns + mem0 insights
5. Return pending habits list + coaching message

**VerifyAndComplete** — handles a single habit completion:
1. Check habit's `verification_policy`
2. If `NONE` → create completion directly (verified=True)
3. If `TEXT` → call `ProofVerifier.verify_text()`, create completion with result
4. If `PHOTO` → call `ProofVerifier.verify_image()`, create completion with result
5. Compute updated streak
6. Return `ProofResult` + streak info

### CheckinSession (Conversation State)

```python
@dataclass
class CheckinSession:
    user_id: int
    habits: list[Habit]
    current_index: int = 0
    results: list[CheckinResult] = field(default_factory=list)
    state: SessionState = SessionState.AWAITING_RESPONSE
    created_at: datetime  # for 24h TTL

    def current_habit(self) -> Habit | None
    def advance(self) -> Habit | None
    def record_skip(self) -> None
    def record_completion(self, completion: Completion) -> None
    def is_complete(self) -> bool
    def is_expired(self) -> bool  # 24h TTL check
    def get_summary(self) -> CompletionSummary
    def to_dict(self) -> dict  # for persistence serialization
    @classmethod
    def from_dict(cls, data: dict) -> CheckinSession
```

`SessionState` enum: `AWAITING_RESPONSE` (yes/no/skip), `AWAITING_PROOF` (waiting for text or photo), `DONE`.

Lives in `context.user_data`, persisted to PostgreSQL via python-telegram-bot's `BasePersistence`.

---

## Infrastructure Layer

### Database (`infrastructure/database/`)

**connection.py** — `DatabaseSessionManager`:
- Async engine via asyncpg
- `DeclarativeBase` (SQLAlchemy 2.0, not legacy `declarative_base()`)
- Configurable pool: `pool_size`, `max_overflow`
- SSL via engine connect_args for Azure PostgreSQL

**models.py** — ORM models:
- `UserModel` — index on `telegram_id` (unique)
- `HabitModel` — composite index on `(user_id, is_active)`, `verification_policy` column (String, stores enum value)
- `CompletionModel` — composite index on `(habit_id, completed_at)`. No `missed` column.

**repositories/** — implement Protocol interfaces. Map ORM ↔ domain entities. `get_completion_dates()` returns `list[date]` for streak computation.

### LLM (`infrastructure/ai/`)

**llm_client.py** — wraps LiteLLM:
- `complete(messages, model, temperature) -> str`
- `complete_with_schema(messages, schema, model, temperature) -> dict`
- LiteLLM handles provider routing by model name prefix
- Provider API keys read from env by LiteLLM automatically

**proof_verifier.py** — implements `ProofVerifier` protocol:
- `verify_text()` — one-shot LLM call with habit context + user's text proof
- `verify_image()` — one-shot vision LLM call with habit context + base64 image
- Returns `ProofResult` with confidence and reasoning

**pattern_analyzer.py** — implements `PatternAnalyzer` protocol:
- `analyze_patterns()` — computes behavioral patterns from completion data:
  - Day-of-week trends (SQL query + Python analysis)
  - Streak patterns (domain Streak computation)
  - Improvement/decline trends (completion rate over rolling windows)
  - Cross-habit correlations
- `generate_coaching_message()` — single LLM call combining:
  - Computed behavioral patterns
  - User insights retrieved from mem0
  - Today's checkin context (which habits pending, current streaks)
  - Returns a short, personal coaching message

### Memory (`infrastructure/memory/`)

**mem0_store.py** — implements `MemoryStore` protocol:
- Wraps `mem0.AsyncMemory` configured with pgvector
- DB config derived from `DATABASE_URL` (parsed into host/port/db/user/password)
- `store_insight(user_id, insight, category)` — stores after each completed check-in
- `get_insights(user_id)` — retrieves relevant memories for coaching context
- Proper error handling with logging, no fire-and-forget

### Persistence (`infrastructure/persistence/`)

**postgres_persistence.py** — implements python-telegram-bot's `BasePersistence`:
- Stores `user_data`/`chat_data`/`bot_data` as JSONB in a `bot_persistence` table
- `CheckinSession` serialized via `to_dict()`/`from_dict()`
- Survives bot restarts and long user gaps (user sends proof 5 hours later)
- 24h TTL on `CheckinSession` — expired sessions cleaned up on load

### Observability (`infrastructure/observability/`)

**tracing.py** — Arize Phoenix integration:
- `setup_tracing(collector_endpoint)` — registers Phoenix OTEL tracer provider, instruments LiteLLM via `openinference-instrumentation-litellm`
- `@trace_handler(name)` — decorator for Telegram handlers. Root span with `user.id`, `user.username`, `message.text` attributes.
- `@trace_operation(name, op_type)` — decorator for use cases and repository methods. Child spans with domain-relevant attributes.
- All LLM calls auto-traced by LiteLLM instrumentor (token counts, latency, model, prompt/completion)
- Optional: disabled when `ENABLE_TRACING=false`

### Config (`infrastructure/config/`)

**settings.py**:
```python
class Settings:
    def __init__(self) -> None:
        self.telegram_bot_token = self._require("TELEGRAM_BOT_TOKEN")
        self.database_url = self._require("DATABASE_URL")
        self.llm_model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        self.llm_temperature = float(os.getenv("LLM_TEMPERATURE", "0.7"))
        self.collector_endpoint = os.getenv("COLLECTOR_ENDPOINT")
        self.enable_tracing = os.getenv("ENABLE_TRACING", "false").lower() == "true"
        self.webhook_url = self._require("WEBHOOK_URL")
        self.webhook_secret = os.getenv("WEBHOOK_SECRET", "")

    def get_mem0_config(self) -> dict:
        """Parse DATABASE_URL into mem0's pgvector config format."""
        ...

    def _require(self, key: str) -> str:
        value = os.getenv(key, "")
        if not value:
            raise ConfigurationError(f"Required env var {key} is not set")
        return value
```

Evaluated at construction time, not import time. Single `DATABASE_URL` for app + mem0 + alembic.

### Logging (`infrastructure/logging/`)

**logger.py** — `structlog` for structured JSON logging. Configured once at startup.

---

## Presentation Layer

### Webhook Setup (`presentation/main.py`)

The composition root. Wires all dependencies via constructor injection:

```python
async def create_application() -> Application:
    settings = Settings()

    if settings.enable_tracing:
        setup_tracing(settings.collector_endpoint)

    # Infrastructure
    session_manager = DatabaseSessionManager(settings.database_url)
    llm_client = LiteLLMClient(model=settings.llm_model, temperature=settings.llm_temperature)
    proof_verifier = LiteLLMProofVerifier(llm_client)
    memory_store = Mem0MemoryStore(settings.get_mem0_config())
    pattern_analyzer = LLMPatternAnalyzer(llm_client, memory_store)
    persistence = PostgresPersistence(session_manager)

    # Use cases — created per-request with fresh DB sessions (via factory)
    # Handlers receive factories, not instances

    app = ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .persistence(persistence)
        .build()

    # Register handlers...
    # Configure webhook...

    return app
```

### Handlers (`presentation/handlers/`)

**command_handlers.py:**
- `/start` → `RegisterUser` use case
- `/add_habit <name> [text|photo]` → `CreateHabit` use case (verification_policy from optional arg, defaults to NONE)
- `/list_habits` → `ListHabits` use case
- `/delete_habit <name>` → `DeleteHabit` use case
- `/help` → static help text

Each handler: parse Telegram update → call use case → format response via formatter → send. ~10 lines max.

**checkin_handlers.py:**
- `/checkin` → create `CheckinSession`, call `StartCheckin` use case, send coaching message, ask about first habit.

**proof_handlers.py:**
- Text messages during active checkin:
  - `AWAITING_RESPONSE` → parse yes/no/skip. "yes" + `requires_proof()` → set `AWAITING_PROOF`. "yes" + no proof needed → call `VerifyAndComplete(policy=NONE)`, advance. "no"/"skip" → record skip, advance.
  - `AWAITING_PROOF` → call `VerifyAndComplete` with text proof, advance.
- Photo messages → call `VerifyAndComplete` with image bytes, advance.
- Session complete → show summary via formatter, clear session.

All handlers decorated with `@trace_handler` for Phoenix spans.

### Formatters (`presentation/formatters.py`)

Separate module for building Telegram message strings:
- `format_habit_list(habits, streaks) -> str`
- `format_checkin_prompt(habit) -> str`
- `format_proof_result(result, streak) -> str`
- `format_checkin_summary(summary) -> str`
- `format_help() -> str`

---

## Infrastructure (Azure / Terragrunt)

### What stays

- Terragrunt + OpenTofu module structure
- Modules: ACR, Key Vault, PostgreSQL, Phoenix, Web App
- Single `live/` environment
- Resource group module (data source for the group selected by `AZURE_RESOURCE_GROUP`)
- Deploy/destroy/bootstrap scripts

### What changes

| Change | Detail |
|--------|--------|
| Webhooks | Web App receives Telegram POSTs. `WEBHOOK_URL` set to App Service URL. |
| Health check | Remove `health_server.py`. Webhook server handles health natively. |
| Env vars | Simplified to 8: `TELEGRAM_BOT_TOKEN`, `LLM_MODEL`, `LLM_TEMPERATURE`, `DATABASE_URL`, `COLLECTOR_ENDPOINT`, `ENABLE_TRACING`, `WEBHOOK_URL`, `WEBHOOK_SECRET`. No more `MEMORY_PG_*` x5. |
| startup.sh | Simplified — no defaults that conflict with `Settings`, just passes through env vars. |
| CI/CD | GitHub Actions: test (testcontainers + VCR) → build Docker → push ACR → restart Web App. |
| Passphrase | `ARM_TOFU_ENCRYPTION_PASSPHRASE` env var. Set as pipeline secret in CI, export locally. |
| F1 tier | Stays F1 with code comment noting B1+ recommended for production (always-on, webhook reliability). |
| Key Vault | Stays 7-day soft delete with code comment noting 90 days for production. |

### Alembic Migration

New initial migration replacing the current one:
- `users` table (id, telegram_id, username, created_at)
- `habits` table (id, user_id, name, description, frequency, verification_policy, is_active, created_at) — adds `verification_policy`, keeps `frequency`
- `completions` table (id, habit_id, completed_at, proof_type, verified, verification_notes) — removes `missed` column
- `bot_persistence` table (key, data, updated_at) — for python-telegram-bot persistence
- `memory_insights` table — managed by mem0 (auto-created)
- Composite indexes: `(user_id, is_active)` on habits, `(habit_id, completed_at)` on completions

---

## Testing

### Stack

- **pytest** + **pytest-asyncio** — async test runner
- **pytest-env** — test environment variables
- **pytest-xdist** — parallel test execution
- **testcontainers** — real PostgreSQL + pgvector per test session
- **VCR.py** — recorded LLM HTTP cassettes
- **prek** — pre-commit hooks (dev dependency)

### Structure

Organized by test type, not by source layer. Maps directly to CI stages.

```
tests/
  unit/                          — pure Python, no IO, fast, run on every commit
    conftest.py                  — in-memory repo fakes, shared test data
    test_habit.py                — entity behavior, verification policy
    test_streak.py               — streak computation from dates
    test_value_objects.py        — TelegramId, HabitName validation
    test_completion_summary.py
    test_checkin_session.py      — state transitions, TTL, serialization
    test_register_user.py        — use case with in-memory repo fakes
    test_create_habit.py
    test_start_checkin.py
    test_verify_and_complete.py
    test_formatters.py           — pure string transforms
  integration/                   — needs testcontainers + VCR, slower
    conftest.py                  — postgres container, test engine, session, VCR config
    cassettes/                   — recorded LLM HTTP responses
    test_repositories.py         — real SQL against testcontainers Postgres
    test_proof_verifier.py       — LLM calls via VCR cassettes
    test_pattern_analyzer.py     — pattern detection logic + VCR for coaching
    test_mem0_store.py           — mem0 against testcontainers + VCR for embeddings
    test_postgres_persistence.py — bot persistence serialization roundtrip
```

- `pytest tests/unit` — seconds, no Docker, local dev loop
- `pytest tests/integration` — needs Docker, testcontainers + VCR cassettes
- CI runs unit first, integration only if unit passes

### Fixtures (following user's established pattern)

```python
@pytest.fixture
def postgres_container() -> Generator[PostgresContainer, None, None]:
    with PostgresContainer("pgvector/pgvector:pg17") as container:
        container.start()
        yield container

@pytest_asyncio.fixture
async def test_engine(postgres_container) -> AsyncGenerator[AsyncEngine, None]:
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
    await engine.dispose()

@pytest_asyncio.fixture
async def test_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    async_session = sessionmaker(
        bind=test_engine, class_=AsyncSession,
        expire_on_commit=False, autoflush=False, autocommit=False
    )
    async with async_session() as session:
        yield session
        await session.rollback()

@pytest.fixture(scope="module")
def vcr_config() -> VCR:
    cassette_dir = Path(__file__).parent / "cassettes"
    cassette_dir.mkdir(exist_ok=True)
    return vcr.VCR(
        cassette_library_dir=str(cassette_dir),
        filter_headers=["authorization", "api-key"],
        ignore_hosts=["localhost", "unix", "docker"],
        record_mode="once",
        match_on=["uri", "body"],
    )
```

### CI

GitHub Actions runs `pytest` with:
- Testcontainers uses Docker-in-Docker service
- VCR replays from committed cassettes (`record_mode="none"` in CI)
- `pytest-xdist` for parallel execution
- No live LLM calls in CI

---

## Project File Structure (final)

```
src/habit_tracker/
  __init__.py
  domain/
    __init__.py
    entities/
      __init__.py
      user.py
      habit.py
      completion.py
    value_objects/
      __init__.py
      telegram_id.py
      habit_name.py
      frequency.py
      verification_policy.py
      proof_result.py
      streak.py
      completion_summary.py
    exceptions.py
  application/
    __init__.py
    ports/
      __init__.py
      repositories.py
      ai_services.py
    dtos/
      __init__.py
      habit_dto.py
      completion_dto.py
      memory_dto.py
      pattern_dto.py
    use_cases/
      __init__.py
      register_user.py
      create_habit.py
      delete_habit.py
      list_habits.py
      start_checkin.py
      verify_and_complete.py
    checkin_session.py
  infrastructure/
    __init__.py
    ai/
      __init__.py
      llm_client.py
      proof_verifier.py
      pattern_analyzer.py
    memory/
      __init__.py
      mem0_store.py
    database/
      __init__.py
      connection.py
      models.py
      repositories/
        __init__.py
        user_repository.py
        habit_repository.py
        completion_repository.py
    persistence/
      __init__.py
      postgres_persistence.py
    observability/
      __init__.py
      tracing.py
    config/
      __init__.py
      settings.py
    logging/
      __init__.py
      logger.py
  presentation/
    __init__.py
    main.py
    formatters.py
    handlers/
      __init__.py
      command_handlers.py
      checkin_handlers.py
      proof_handlers.py
tests/
  unit/
  integration/
    cassettes/
alembic/
infra/
scripts/
.github/workflows/
```

---

## Environment Variables

```
TELEGRAM_BOT_TOKEN     — Telegram bot API token
LLM_MODEL              — LiteLLM model identifier (e.g. gpt-4o-mini, claude-sonnet-4-20250514)
LLM_TEMPERATURE        — LLM temperature (default: 0.7)
DATABASE_URL            — PostgreSQL connection URL (used by app, mem0, alembic)
COLLECTOR_ENDPOINT     — Phoenix OTEL collector URL
ENABLE_TRACING         — true/false (default: false)
WEBHOOK_URL            — Public URL for Telegram webhook
WEBHOOK_SECRET         — Secret token to validate webhook requests
```

Provider-specific API keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.) read from env by LiteLLM automatically based on `LLM_MODEL` prefix.

---

## Dependencies

### Production
- python-telegram-bot[webhooks]
- sqlalchemy[asyncio]
- asyncpg
- litellm
- mem0ai
- arize-phoenix-otel
- openinference-instrumentation-litellm
- structlog
- alembic
- psycopg2-binary (alembic sync migrations)
- python-dotenv
- greenlet

### Dev
- pytest
- pytest-asyncio
- pytest-env
- pytest-xdist
- testcontainers[postgres]
- vcrpy
- prek (pre-commit)
