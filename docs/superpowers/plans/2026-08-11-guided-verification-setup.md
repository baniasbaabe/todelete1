# Guided Verification Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recommend and confirm a verification policy for every new habit, and configure legacy `none` habits once during check-in so photo and quiz proof flows run as intended.

**Architecture:** Add an application recommender port with an LLM adapter and deterministic fallback, then persist guided-setup state as JSON-safe Telegram `user_data`. New-habit confirmation happens before creation; legacy-habit configuration updates the owned habit and keeps the check-in on the same habit.

**Tech Stack:** Python 3.13, python-telegram-bot, Groq through the existing `LLMClient`, SQLAlchemy repositories, pytest/pytest-asyncio, VCR.py, Ruff, Pyrefly.

## Global Constraints

- Groq requests keep `reasoning_effort="none"`; no model reasoning appears in Telegram replies.
- A recommendation is never saved until the user confirms or replaces it.
- `/add_habit <name> --verify text|photo|quiz` remains immediate and backward compatible.
- Configuring an existing `none` habit must not advance or complete it.
- Telegram `user_data` contains only JSON-safe primitives.
- No database migration or runtime DDL.
- Python 3.13 types, 120-character lines, and ASCII punctuation are required.

## File Map

- `application/ports/ai_services.py`: add `VerificationRecommender`.
- `application/services/verification_recommendation.py`: deterministic fallback and safe wrapper.
- `infrastructure/ai/verification_recommender.py`: LLM enum adapter.
- `application/use_cases/set_habit_verification.py`: ownership-checked policy update.
- `presentation/handlers/verification_setup.py`: pending state, confirmed-`none` state, choices, and prompts.
- `application/checkin_session.py`: check-in setup state serialization.
- `presentation/dependencies.py` and `presentation/main.py`: dependency wiring.
- Command, check-in, proof handlers, and formatters: guided interaction.
- Unit tests cover each boundary; VCR integration tests pin the real Groq request contract.
- Repository-backed handler integration tests cover complete guided photo and quiz journeys.

---

### Task 1: Recommendation Port, Fallback, and LLM Adapter

**Files:**

- Create: `src/habit_tracker/application/services/__init__.py`
- Create: `src/habit_tracker/application/services/verification_recommendation.py`
- Modify: `src/habit_tracker/application/ports/ai_services.py`
- Create: `src/habit_tracker/infrastructure/ai/verification_recommender.py`
- Create: `tests/unit/test_verification_recommender.py`

**Interfaces:**

- Consumes: `HabitName`, `VerificationPolicy`, `LLMClient.complete_json`.
- Produces: `VerificationRecommender.recommend`, `fallback_policy`, `SafeVerificationRecommender`, `LLMVerificationRecommender`.

- [ ] **Step 1: Write the failing fallback tests**

```python
def test_gym_falls_back_to_photo() -> None:
    assert fallback_policy(HabitName("Gym")) is VerificationPolicy.PHOTO


def test_learning_python_falls_back_to_quiz() -> None:
    assert fallback_policy(HabitName("Learn Python")) is VerificationPolicy.QUIZ


def test_unknown_habit_falls_back_to_text() -> None:
    assert fallback_policy(HabitName("Call my parents")) is VerificationPolicy.TEXT
```

- [ ] **Step 2: Run the tests and confirm the missing-module failure**

```bash
uv run pytest tests/unit/test_verification_recommender.py -v
```

- [ ] **Step 3: Add the port and deterministic fallback**

Add the protocol:

```python
class VerificationRecommender(Protocol):
    async def recommend(self, habit_name: HabitName) -> VerificationPolicy: ...
```

Implement learning terms before observable exercise terms so `learn swimming`
selects a quiz:

```python
LEARNING_TERMS = (
    "learn", "study", "read", "course", "practice", "python", "programming",
    "coding", "language", "german", "spanish", "french",
)
PHOTO_TERMS = ("gym", "workout", "run", "walk", "cycle", "yoga", "swim")


def fallback_policy(habit_name: HabitName) -> VerificationPolicy:
    normalized = habit_name.value.casefold()
    if any(term in normalized for term in LEARNING_TERMS):
        return VerificationPolicy.QUIZ
    if any(term in normalized for term in PHOTO_TERMS):
        return VerificationPolicy.PHOTO
    return VerificationPolicy.TEXT
```

- [ ] **Step 4: Run the fallback tests and confirm they pass**

```bash
uv run pytest tests/unit/test_verification_recommender.py -v
```

- [ ] **Step 5: Add failing adapter and fallback-wrapper tests**

Use a stub `complete_json` client and cover valid `quiz`, valid `none`, missing
`verification_policy`, an unknown value, and a provider exception:

```python
async def test_llm_recommender_parses_supported_enum() -> None:
    llm = StubLLM({"verification_policy": "quiz"})
    result = await LLMVerificationRecommender(llm).recommend(HabitName("Learn Python"))
    assert result is VerificationPolicy.QUIZ


async def test_safe_recommender_uses_name_fallback_on_provider_error() -> None:
    delegate = LLMVerificationRecommender(StubLLM(error=RuntimeError("offline")))
    result = await SafeVerificationRecommender(delegate).recommend(HabitName("Gym"))
    assert result is VerificationPolicy.PHOTO
```

- [ ] **Step 6: Implement the adapter and wrapper**

The LLM adapter sends only classification instructions and parses one field:

```python
class LLMVerificationRecommender:
    def __init__(self, llm_client: LLMClient) -> None:
        self._llm = llm_client

    async def recommend(self, habit_name: HabitName) -> VerificationPolicy:
        result = await self._llm.complete_json(
            [
                {
                    "role": "system",
                    "content": (
                        "Recommend habit verification. Return JSON with exactly one key, "
                        "verification_policy, valued photo, quiz, text, or none. Use photo "
                        "for visible activity, quiz for learning, text for written evidence, "
                        "and none only when verification is impractical."
                    ),
                },
                {"role": "user", "content": f"Habit: {habit_name.value}"},
            ],
            temperature=0.0,
        )
        return VerificationPolicy(str(result["verification_policy"]).casefold())
```

`SafeVerificationRecommender` catches failures at this external boundary, logs
without including the habit name, and returns `fallback_policy(habit_name)`.

- [ ] **Step 7: Verify and commit Task 1**

```bash
uv run pytest tests/unit/test_verification_recommender.py -v
uv run ruff check src/habit_tracker/application/ports/ai_services.py src/habit_tracker/application/services src/habit_tracker/infrastructure/ai/verification_recommender.py tests/unit/test_verification_recommender.py
uv run pyrefly check
git add src/habit_tracker/application/ports/ai_services.py src/habit_tracker/application/services src/habit_tracker/infrastructure/ai/verification_recommender.py tests/unit/test_verification_recommender.py
git commit -m "feat: recommend habit verification policies"
```

---

### Task 2: Ownership-Checked Existing-Habit Update

**Files:**

- Create: `src/habit_tracker/application/use_cases/set_habit_verification.py`
- Create: `tests/unit/test_set_habit_verification.py`

**Interfaces:**

- Consumes: user and habit repository find/save methods.
- Produces: `SetHabitVerification.execute(telegram_id, habit_id, policy) -> Habit`.

- [ ] **Step 1: Write failing success and ownership tests**

```python
async def test_updates_owned_active_habit() -> None:
    users = InMemoryUserRepository()
    habits = InMemoryHabitRepository()
    await RegisterUser(users).execute(TelegramId(111))
    habit = await CreateHabit(users, habits).execute(TelegramId(111), HabitName("Gym"))
    updated = await SetHabitVerification(users, habits).execute(
        TelegramId(111), habit.id, VerificationPolicy.PHOTO
    )
    assert updated.verification_policy is VerificationPolicy.PHOTO
    assert (await habits.find_by_id(habit.id)).verification_policy is VerificationPolicy.PHOTO


async def test_rejects_habit_owned_by_another_user() -> None:
    users = InMemoryUserRepository()
    habits = InMemoryHabitRepository()
    await RegisterUser(users).execute(TelegramId(111))
    await RegisterUser(users).execute(TelegramId(222))
    habit = await CreateHabit(users, habits).execute(TelegramId(222), HabitName("Gym"))
    with pytest.raises(HabitNotFoundError):
        await SetHabitVerification(users, habits).execute(
            TelegramId(111), habit.id, VerificationPolicy.PHOTO
        )
```

Also cover missing user, missing habit, and inactive habit.

- [ ] **Step 2: Run tests and confirm the missing-use-case failure**

```bash
uv run pytest tests/unit/test_set_habit_verification.py -v
```

- [ ] **Step 3: Implement exact ownership and active checks**

```python
class SetHabitVerification:
    def __init__(self, user_repo: UserRepository, habit_repo: HabitRepository) -> None:
        self._user_repo = user_repo
        self._habit_repo = habit_repo

    async def execute(
        self, telegram_id: TelegramId, habit_id: int, policy: VerificationPolicy
    ) -> Habit:
        user = await self._user_repo.find_by_telegram_id(telegram_id)
        if user is None or user.id is None:
            raise UserNotFoundError(f"User with telegram_id {telegram_id.value} not found")
        habit = await self._habit_repo.find_by_id(habit_id)
        if habit is None or habit.user_id != user.id or not habit.is_active:
            raise HabitNotFoundError(f"Habit {habit_id} not found")
        habit.verification_policy = policy
        return await self._habit_repo.save(habit)
```

- [ ] **Step 4: Verify and commit Task 2**

```bash
uv run pytest tests/unit/test_set_habit_verification.py tests/unit/test_create_habit.py tests/unit/test_delete_list_habits.py -v
git add src/habit_tracker/application/use_cases/set_habit_verification.py tests/unit/test_set_habit_verification.py
git commit -m "feat: update habit verification policy"
```

---

### Task 3: JSON-Safe Setup and Check-in Session State

**Files:**

- Create: `src/habit_tracker/presentation/handlers/verification_setup.py`
- Modify: `src/habit_tracker/application/checkin_session.py`
- Create: `tests/unit/test_verification_setup_state.py`
- Modify: `tests/unit/test_checkin_session.py`

**Interfaces:**

- Consumes: `context.user_data`, `Habit`, `HabitName`, `VerificationPolicy`.
- Produces: pending-state CRUD, configured-`none` helpers, choice parsing, setup formatting, and serialized check-in recommendation state.

- [ ] **Step 1: Write failing JSON-state and choice tests**

```python
def test_pending_setup_round_trips_as_plain_data() -> None:
    user_data: dict = {}
    setup = PendingHabitSetup(HabitName("Gym"), VerificationPolicy.PHOTO)
    save_pending_setup(user_data, setup)
    assert user_data[PENDING_HABIT_KEY] == {"name": "Gym", "recommendation": "photo"}
    assert load_pending_setup(user_data) == setup


def test_yes_selects_recommendation() -> None:
    assert parse_setup_choice(" YES ", VerificationPolicy.QUIZ) is VerificationPolicy.QUIZ


@pytest.mark.parametrize("choice", ["photo", "QUIZ", " Text ", "none"])
def test_explicit_choice_selects_exact_policy(choice: str) -> None:
    assert parse_setup_choice(choice, VerificationPolicy.PHOTO).value == choice.strip().lower()


def test_confirmed_none_is_keyed_by_habit_id() -> None:
    user_data: dict = {}
    mark_none_configured(user_data, 42)
    assert is_none_configured(user_data, 42)
    assert not is_none_configured(user_data, 43)
```

Also prove corrupt pending data is removed, `cancel` is distinguished from
invalid input, and configured IDs are stored as a JSON-safe integer list.

- [ ] **Step 2: Run tests and confirm the missing-module failure**

```bash
uv run pytest tests/unit/test_verification_setup_state.py -v
```

- [ ] **Step 3: Implement helpers and exact prompt copy**

Use `PENDING_HABIT_KEY = "pending_habit_setup"` and
`CONFIGURED_NONE_KEY = "configured_none_habit_ids"`. `parse_setup_choice`
returns the recommendation for `yes`, an enum for an explicit policy, and
`None` for invalid input. `is_setup_cancel` handles cancellation separately.

```python
def format_setup_prompt(name: HabitName, recommendation: VerificationPolicy) -> str:
    return (
        f'For "{name.value}", I recommend {recommendation.value} verification.\n'
        "Reply 'yes' to use it, or choose: photo, quiz, text, none.\n"
        "Reply 'cancel' to stop."
    )
```

- [ ] **Step 4: Write failing session serialization tests**

```python
def test_verification_setup_state_round_trips(sample_habit: Habit) -> None:
    session = CheckinSession.start(1, [sample_habit])
    session.state = SessionState.AWAITING_VERIFICATION_SETUP
    session.verification_recommendation = VerificationPolicy.PHOTO
    restored = CheckinSession.from_dict(session.to_dict())
    assert restored.state is SessionState.AWAITING_VERIFICATION_SETUP
    assert restored.verification_recommendation is VerificationPolicy.PHOTO


def test_old_session_without_recommendation_still_decodes(sample_session: CheckinSession) -> None:
    data = sample_session.to_dict()
    data.pop("verification_recommendation")
    restored = CheckinSession.from_dict(data)
    assert restored.verification_recommendation is None
```

- [ ] **Step 5: Extend `CheckinSession` compatibly**

Add `AWAITING_VERIFICATION_SETUP = "awaiting_verification_setup"`, add
`verification_recommendation: VerificationPolicy | None = None`, clear it in
`advance`, serialize the value or `None`, and decode a missing key as `None`.

- [ ] **Step 6: Verify and commit Task 3**

```bash
uv run pytest tests/unit/test_verification_setup_state.py tests/unit/test_checkin_session.py -v
git add src/habit_tracker/presentation/handlers/verification_setup.py src/habit_tracker/application/checkin_session.py tests/unit/test_verification_setup_state.py tests/unit/test_checkin_session.py
git commit -m "feat: persist verification setup state"
```

---

### Task 4: Guided Creation and Dependency Wiring

**Files:**

- Modify: `src/habit_tracker/presentation/dependencies.py`
- Modify: `src/habit_tracker/presentation/main.py`
- Modify: `src/habit_tracker/presentation/handlers/command_handlers.py`
- Modify: `src/habit_tracker/presentation/handlers/proof_handlers.py`
- Modify: `src/habit_tracker/presentation/formatters.py`
- Modify: `tests/unit/conftest.py`
- Create: `tests/unit/test_guided_habit_setup.py`
- Modify: `tests/unit/test_wiring.py`
- Modify: `tests/unit/test_command_parsing.py`
- Modify: `tests/unit/test_formatters.py`

**Interfaces:**

- Consumes: Task 1 recommender, Task 3 pending-state helpers, existing `CreateHabit`.
- Produces: guided `/add_habit` setup and confirmation through the existing text handler.

- [ ] **Step 1: Add a failing dependency-wiring contract**

Add this fake and pass it to every `Dependencies` test fixture:

```python
class FakeVerificationRecommender:
    def __init__(self, policy: VerificationPolicy = VerificationPolicy.TEXT) -> None:
        self.policy = policy
        self.names: list[str] = []

    async def recommend(self, habit_name: HabitName) -> VerificationPolicy:
        self.names.append(habit_name.value)
        return self.policy
```

Assert the installed object is returned unchanged from `dependencies(context)`.

- [ ] **Step 2: Add and wire the production dependency**

Add `verification_recommender: VerificationRecommender` to `Dependencies` and
share the existing Groq client:

```python
verification_recommender = SafeVerificationRecommender(LLMVerificationRecommender(llm))
dependencies = Dependencies(
    db=db,
    proof_verifier=proof_verifier,
    memory_store=memory_store,
    pattern_analyzer=pattern_analyzer,
    verification_recommender=verification_recommender,
)
```

- [ ] **Step 3: Write failing guided-creation tests**

Create an in-memory handler environment like `test_checkin_flow.py` and cover:

```python
async def test_add_without_verify_waits_for_confirmation(env) -> None:
    command = update_for("/add_habit Gym")
    await add_habit_handler(command, env.context)
    assert await env.habits.find_active_by_user(env.user.id) == []
    assert env.context.user_data["pending_habit_setup"] == {
        "name": "Gym",
        "recommendation": "photo",
    }
    assert "recommend photo" in command.message.reply_text.await_args.args[0].lower()


async def test_yes_creates_with_recommended_policy(env) -> None:
    await add_habit_handler(update_for("/add_habit Gym"), env.context)
    await text_response_handler(update_for("yes"), env.context)
    habit = (await env.habits.find_active_by_user(env.user.id))[0]
    assert habit.verification_policy is VerificationPolicy.PHOTO
    assert "pending_habit_setup" not in env.context.user_data


async def test_explicit_choice_overrides_recommendation(env) -> None:
    await add_habit_handler(update_for("/add_habit Gym"), env.context)
    await text_response_handler(update_for("quiz"), env.context)
    habit = (await env.habits.find_active_by_user(env.user.id))[0]
    assert habit.verification_policy is VerificationPolicy.QUIZ
```

Also cover `cancel`, invalid input, duplicate failure retaining pending state,
case-insensitive input, replacing a pending setup, explicit `none`, and
`--verify photo` bypassing the recommender.

- [ ] **Step 4: Run tests and confirm current immediate creation fails them**

```bash
uv run pytest tests/unit/test_guided_habit_setup.py tests/unit/test_wiring.py tests/unit/test_command_parsing.py -v
```

- [ ] **Step 5: Start pending setup when `--verify` is absent**

Keep `_parse_add_habit_args` unchanged. When it yields `NONE`, recommend a
policy, save a `PendingHabitSetup`, and reply with `format_setup_prompt` without
opening a creation transaction. A second command overwrites pending state and
prefixes `Replacing the pending setup with "<new name>".` Explicit non-`NONE`
policies keep the current immediate transaction.

- [ ] **Step 6: Confirm pending setup after check-in routing**

Add `_handle_pending_habit_setup(update, context) -> bool` to
`proof_handlers.py`. Return `False` with no pending setup. Otherwise:

- `cancel`: clear it and reply `Habit setup cancelled.`
- invalid: repeat the prompt and retain state.
- valid: create and commit with the selected policy, mark a newly saved `none`
  habit as configured, clear state, and report the policy.
- creation failure: retain state and send the existing friendly error.

Call this helper only after proving no active check-in exists, preserving the
approved check-in-first routing priority.

- [ ] **Step 7: Update help and verify Task 4**

Use these two help lines:

```text
/add_habit <name> - Add a habit and choose verification
/add_habit <name> --verify text|photo|quiz - Add immediately
```

Run and commit:

```bash
uv run pytest tests/unit/test_guided_habit_setup.py tests/unit/test_wiring.py tests/unit/test_command_parsing.py tests/unit/test_formatters.py -v
git add src/habit_tracker/presentation/dependencies.py src/habit_tracker/presentation/main.py src/habit_tracker/presentation/handlers/command_handlers.py src/habit_tracker/presentation/handlers/proof_handlers.py src/habit_tracker/presentation/formatters.py tests/unit/conftest.py tests/unit/test_guided_habit_setup.py tests/unit/test_wiring.py tests/unit/test_command_parsing.py tests/unit/test_formatters.py
git commit -m "feat: confirm verification when adding habits"
```

---

### Task 5: One-Time Setup for Existing Habits During Check-in

**Files:**

- Modify: `src/habit_tracker/presentation/handlers/verification_setup.py`
- Modify: `src/habit_tracker/presentation/handlers/checkin_handlers.py`
- Modify: `src/habit_tracker/presentation/handlers/proof_handlers.py`
- Modify: `src/habit_tracker/presentation/formatters.py`
- Modify: `tests/unit/test_checkin_flow.py`
- Modify: `tests/unit/test_quiz_verification.py`

**Interfaces:**

- Consumes: `SetHabitVerification`, setup helpers, session recommendation state, and recommender dependency.
- Produces: one common current-habit preparation path at start, resume, and advancement.

- [ ] **Step 1: Write failing legacy-habit setup tests**

Mark unrelated old `NONE` fixtures as explicitly configured, then add focused
tests:

```python
async def test_legacy_none_habit_starts_with_setup_prompt(env) -> None:
    await _seed(env, policy=VerificationPolicy.NONE)
    update = _update()
    await checkin_handler(update, env.context)
    session = env.context.user_data["checkin_session"]
    assert session["state"] == "awaiting_verification_setup"
    assert session["verification_recommendation"] == "photo"
    assert "recommend photo" in update.message.reply_text.await_args.args[0].lower()


async def test_selecting_photo_updates_without_advancing(env) -> None:
    await _seed(env, policy=VerificationPolicy.NONE)
    await checkin_handler(_update(), env.context)
    reply = _update("yes")
    await text_response_handler(reply, env.context)
    session = env.context.user_data["checkin_session"]
    assert session["current_index"] == 0
    assert session["state"] == "awaiting_response"
    assert session["habits"][0]["verification_policy"] == "photo"
    assert "submit photo proof" in reply.message.reply_text.await_args.args[0].lower()
```

Also cover explicit `quiz`, `text`, and `none`; invalid input; `skip`; resumed
setup; update failure; and preparation of a second legacy habit after the first
advances.

- [ ] **Step 2: Write failing proof-continuation tests**

For photo, prove setup -> normal prompt -> `yes` -> `AWAITING_PROOF`. For quiz,
prove setup -> normal prompt -> `yes` -> topic -> generated question -> answer
-> exactly one completion and session finish. Assert repository state as well
as reply text.

- [ ] **Step 3: Run flow tests and confirm the old behavior fails**

```bash
uv run pytest tests/unit/test_checkin_flow.py tests/unit/test_quiz_verification.py -v
```

- [ ] **Step 4: Add the common async preparation helper**

Place this logic in `verification_setup.py` so both handlers use it:

```python
async def prepare_current_habit(
    session: CheckinSession,
    recommender: VerificationRecommender,
    user_data: dict,
) -> str:
    habit = session.current_habit()
    if habit is None:
        return ""
    needs_setup = (
        habit.verification_policy is VerificationPolicy.NONE
        and habit.id is not None
        and not is_none_configured(user_data, habit.id)
    )
    if needs_setup:
        if session.verification_recommendation is None:
            session.verification_recommendation = await recommender.recommend(habit.name)
        session.state = SessionState.AWAITING_VERIFICATION_SETUP
        return format_setup_prompt(habit.name, session.verification_recommendation)
    session.state = SessionState.AWAITING_RESPONSE
    session.verification_recommendation = None
    return format_checkin_prompt(habit)
```

Call it for a fresh `/checkin`, a resumed `/checkin`, and the next habit after
`session.advance()`.

- [ ] **Step 5: Handle an existing-habit setup response**

Before proof, quiz, and affirmative branches, handle
`AWAITING_VERIFICATION_SETUP`. Preserve global `skip`: record a skip and
advance, leaving the habit unconfigured for a later day.

For a valid selection:

1. Resolve `yes` to `session.verification_recommendation`.
2. Execute `SetHabitVerification` using the Telegram user and current habit ID.
3. Commit and replace `session.habits[session.current_index]` with the returned habit.
4. Mark explicit `none` in `user_data`.
5. Clear the recommendation, set `AWAITING_RESPONSE`, and save the session.
6. Reply `Verification set to <policy>.` followed by the normal prompt.

This branch must not call `advance`, `record_completion`, or
`VerifyAndComplete`.

- [ ] **Step 6: Verify and commit Task 5**

```bash
uv run pytest tests/unit/test_checkin_flow.py tests/unit/test_quiz_verification.py tests/unit/test_formatters.py -v
git add src/habit_tracker/presentation/handlers/verification_setup.py src/habit_tracker/presentation/handlers/checkin_handlers.py src/habit_tracker/presentation/handlers/proof_handlers.py src/habit_tracker/presentation/formatters.py tests/unit/test_checkin_flow.py tests/unit/test_quiz_verification.py tests/unit/test_formatters.py
git commit -m "feat: configure legacy habits during checkin"
```

---

### Task 6: Real Groq Contract and Full Verification

**Files:**

- Create: `tests/integration/test_guided_verification_flow.py`
- Create: `tests/integration/test_verification_recommender.py`
- Create: `tests/integration/cassettes/test_verification_recommender/test_gym_recommends_photo.yaml`
- Create: `tests/integration/cassettes/test_verification_recommender/test_learning_python_recommends_quiz.yaml`
- Modify only when command documentation differs: `README.md`

**Interfaces:**

- Consumes: SQLAlchemy repositories, production handlers, fake proof services, production `GroqLLMClient`, and VCR.
- Produces: repository-backed photo/quiz journeys and replayable evidence that recommendations keep reasoning disabled.

- [ ] **Step 1: Write repository-backed guided-flow integration tests**

Use `test_session` with `SQLAlchemyUserRepository`, `SQLAlchemyHabitRepository`,
and `SQLAlchemyCompletionRepository`. Provide a test `Dependencies` subclass
whose `unit_of_work` yields those repositories and whose external services are
the existing fakes.

The photo journey must perform these real handlers in order:

1. Register the Telegram user.
2. `/add_habit Gym` with a photo recommendation.
3. `yes` to create the habit.
4. `/checkin`, then `yes` to request photo proof.
5. `photo_response_handler` using a mocked Telegram file download.
6. Query the real completion repository and assert one verified `PHOTO` completion.

The quiz journey must perform:

1. `/add_habit Learn Python` with a quiz recommendation.
2. `yes` to create it.
3. `/checkin`, `yes`, a topic, and an answer through the real handlers.
4. Query and assert one verified `QUIZ` completion.

Both tests assert the session finishes and the habit policy persisted in
PostgreSQL. They do not call Groq; the separate VCR tests own that boundary.

- [ ] **Step 2: Run the guided-flow integration tests**

```bash
uv run pytest tests/integration/test_guided_verification_flow.py -v
```

Expected: both flows pass with Docker available.

- [ ] **Step 3: Write provider-contract tests**

```python
async def test_gym_recommends_photo(cassette, app_settings: Settings) -> None:
    llm = GroqLLMClient(
        app_settings.groq_api_key, app_settings.llm_model, app_settings.llm_temperature
    )
    result = await LLMVerificationRecommender(llm).recommend(HabitName("Gym workout"))
    request = next(request for request in cassette.requests if request.uri.endswith("/chat/completions"))
    body = json.loads(request.body)
    assert result is VerificationPolicy.PHOTO
    assert body["reasoning_effort"] == "none"
    assert body["response_format"] == {"type": "json_object"}


async def test_learning_python_recommends_quiz(cassette, app_settings: Settings) -> None:
    llm = GroqLLMClient(
        app_settings.groq_api_key, app_settings.llm_model, app_settings.llm_temperature
    )
    result = await LLMVerificationRecommender(llm).recommend(HabitName("Learn Python"))
    assert result is VerificationPolicy.QUIZ
```

- [ ] **Step 4: Record once, then replay the cassettes**

```bash
RECORD_CASSETTES=1 uv run pytest tests/integration/test_verification_recommender.py -v
uv run pytest tests/integration/test_verification_recommender.py -v
```

Confirm authorization headers are scrubbed and request bodies contain
`reasoning_effort: none`.

- [ ] **Step 5: Run complete verification**

```bash
uv run pytest tests/unit -q
uv run pytest tests/integration -q
uv run ruff format --check src tests
uv run ruff check src tests
uv run pyrefly check
```

Expected: all unit and integration tests pass; Docker is required by the
integration suite.

- [ ] **Step 6: Inspect scope and commit the final contract**

```bash
git status --short
git diff --check
git diff --stat HEAD
git add tests/integration/test_guided_verification_flow.py tests/integration/test_verification_recommender.py tests/integration/cassettes/test_verification_recommender README.md
git commit -m "test: cover guided verification recommendations"
```

Before committing, ensure no environment files, credentials, unrelated user
changes, migrations, or generated caches are staged.
