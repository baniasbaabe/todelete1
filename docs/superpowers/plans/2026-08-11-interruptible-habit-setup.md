# Interruptible Habit Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace verification flags with an explicit guided choice, make habit setup pause and resume active check-ins safely, and hide routine Mem0 fallback noise without hiding errors.

**Architecture:** Keep the JSON-safe pending setup as a temporary overlay above the persisted check-in. Route ordinary text to the overlay first, surround commands with pre/post lifecycle handlers, and centralize phase-aware check-in restoration. Raise only the two noisy Mem0 logger namespaces to `ERROR`.

**Tech Stack:** Python 3.13, python-telegram-bot, pytest/pytest-asyncio, SQLAlchemy asyncio, PostgreSQL/Testcontainers, structlog, Ruff, Pyrefly, uv.

## Global Constraints

- `/add_habit <name>` is the only advertised and implemented creation syntax.
- Treat the complete command tail as the name; do not recognize or reject legacy verification flags specially.
- Setup accepts only `photo`, `quiz`, `text`, `none`, and `cancel`; `yes` is invalid.
- Pending add setup has text-routing priority over an active check-in.
- Preserve a check-in until completion and restore its exact phase after setup.
- Commands cancel pending add setup, run normally, and then restore a check-in unless `/checkin` already did or `/add_habit` created a newer overlay.
- Do not add spaCy, runtime model downloads, callback buttons, or `ConversationHandler`.
- Keep Mem0 `ERROR` and `CRITICAL` records visible.
- Alembic remains the only schema owner; no application DDL.
- Use ASCII punctuation in Python strings and docstrings for Ruff `RUF002`.
- Testcontainers Ryuk stays enabled.

---

### Task 1: Flag-Free Explicit Verification Choice

**Files:**
- Modify: `src/habit_tracker/presentation/handlers/verification_setup.py:56-105`
- Modify: `src/habit_tracker/presentation/handlers/command_handlers.py:1-133`
- Modify: `src/habit_tracker/presentation/handlers/proof_handlers.py:39-194`
- Modify: `src/habit_tracker/presentation/formatters.py:9-19`
- Modify: `tests/unit/test_verification_setup_state.py:36-79`
- Modify: `tests/unit/test_guided_habit_setup.py:75-272`
- Modify: `tests/unit/test_checkin_flow.py:264-328`
- Modify: `tests/unit/test_formatters.py`
- Delete: `tests/unit/test_command_parsing.py`

**Interfaces:**
- Consumes: `HabitName`, `VerificationPolicy`, `PendingHabitSetup`, `GetRegisteredUser`, and `VerificationRecommender.recommend`.
- Produces: `parse_setup_choice(choice: str) -> VerificationPolicy | None`, explicit-choice prompts, and an add handler that always stores pending setup.

- [ ] **Step 1: Write failing choice and prompt tests**

Replace the recommendation-confirmation assertions in `tests/unit/test_verification_setup_state.py`:

```python
def test_yes_is_not_a_setup_choice() -> None:
    assert parse_setup_choice(" YES ") is None


@pytest.mark.parametrize("choice", ["photo", "QUIZ", " Text ", "none"])
def test_explicit_choice_selects_exact_policy(choice: str) -> None:
    assert parse_setup_choice(choice).value == choice.strip().lower()


def test_format_setup_prompt_requires_an_explicit_choice() -> None:
    assert format_setup_prompt(HabitName("Gym"), VerificationPolicy.PHOTO) == (
        'For "Gym", I recommend photo verification.\n'
        "Choose: quiz, photo, text, or none.\n"
        "Reply 'cancel' to stop."
    )
```

Update cancel assertions to call `parse_setup_choice("cancel")` and `parse_setup_choice("maybe")` with one argument.

- [ ] **Step 2: Write failing add-handler and help tests**

In `tests/unit/test_guided_habit_setup.py`, replace explicit-flag and `yes` cases with:

```python
async def test_add_habit_always_waits_for_explicit_choice(env) -> None:
    command = update_for("/add_habit Learning Python")

    await add_habit_handler(command, env.context)

    assert await env.habits.find_active_by_user(env.user.id) == []
    assert env.context.user_data["pending_habit_setup"] == {
        "name": "Learning Python",
        "recommendation": "photo",
    }
    prompt = command.message.reply_text.await_args.args[0]
    assert "Choose: quiz, photo, text, or none." in prompt
    assert "yes" not in prompt.lower()


async def test_add_habit_treats_the_complete_tail_as_the_name(env) -> None:
    await add_habit_handler(update_for("/add_habit Learning Python --verify quiz"), env.context)

    assert env.context.user_data["pending_habit_setup"]["name"] == "Learning Python --verify quiz"
    assert env.recommender.names == ["Learning Python --verify quiz"]


async def test_yes_repeats_prompt_without_creating(env) -> None:
    await add_habit_handler(update_for("/add_habit Gym"), env.context)
    reply = update_for("yes")

    await text_response_handler(reply, env.context)

    assert await env.habits.find_active_by_user(env.user.id) == []
    assert env.context.user_data["pending_habit_setup"]["name"] == "Gym"
    assert "Choose: quiz, photo, text, or none." in reply.message.reply_text.await_args.args[0]
```

Delete immediate explicit-creation, recommendation-reuse, and explicit-cleanup tests. Change the duplicate case to choose `"photo"`. Preserve tests for registration-before-recommendation, cancellation, invalid input, case folding, configured `none`, and missing `user_data`.

Replace the old prefix-based replacement test with the handler-level state
contract; Task 3 separately covers the command interruption notice:

```python
async def test_second_add_replaces_pending_state(env) -> None:
    await add_habit_handler(update_for("/add_habit Gym"), env.context)

    await add_habit_handler(update_for("/add_habit Read"), env.context)

    assert env.context.user_data["pending_habit_setup"]["name"] == "Read"
    assert env.recommender.names == ["Gym", "Read"]
```

In `tests/unit/test_formatters.py`, assert `format_help()` contains one `/add_habit <name>` line and no `--verify`.

In `tests/unit/test_checkin_flow.py`, replace
`test_selecting_recommended_photo_updates_without_advancing` with:

```python
async def test_yes_is_invalid_during_existing_habit_setup(self, env) -> None:
    await _seed(env, policy=VerificationPolicy.NONE, configured_none=False)
    await checkin_handler(_update(), env.context)
    reply = _update("yes")

    await text_response_handler(reply, env.context)

    session = env.context.user_data["checkin_session"]
    assert session["state"] == "awaiting_verification_setup"
    assert session["habits"][0]["verification_policy"] == "none"
    assert "Choose: quiz, photo, text, or none." in reply.message.reply_text.await_args.args[0]
    env.uow_session.commit.assert_not_awaited()
```

- [ ] **Step 3: Run focused tests and verify RED**

```bash
uv run pytest tests/unit/test_verification_setup_state.py tests/unit/test_guided_habit_setup.py tests/unit/test_checkin_flow.py tests/unit/test_formatters.py -q
```

Expected: failures show `yes` is still accepted, old prompt copy, immediate flag creation, and flag help text.

- [ ] **Step 4: Implement the minimal choice parser and prompts**

In `verification_setup.py`:

```python
def parse_setup_choice(choice: str) -> VerificationPolicy | None:
    """Return an explicit verification policy or ``None``."""
    try:
        return VerificationPolicy(choice.strip().lower())
    except ValueError:
        return None
```

Use this setup copy:

```python
return (
    f'For "{name.value}", I recommend {recommendation.value} verification.\n'
    "Choose: quiz, photo, text, or none.\n"
    "Reply 'cancel' to stop."
)
```

Apply the same explicit-choice line to the check-in setup prompt, followed by `"Reply 'skip' to skip this habit."`.

Update both setup branches in `proof_handlers.py` to call
`parse_setup_choice(update.message.text)` with one argument. Ordinary check-in
affirmatives remain unchanged.

- [ ] **Step 5: Remove the flag parser and immediate creation branch**

In `command_handlers.py`, delete `_parse_add_habit_args`, `_INVALID_VERIFICATION`, the immediate `CreateHabit` branch, and now-unused imports. Set:

```python
_ADD_HABIT_USAGE = "Usage: /add_habit <name>"
```

Extract the name directly and always save pending setup after registration:

```python
args = update.message.text.split(maxsplit=1)
if len(args) < 2:
    await update.message.reply_text(_ADD_HABIT_USAGE)
    return

try:
    habit_name = HabitName(args[1].strip())
except ValueError as exc:
    await update.message.reply_text(str(exc))
    return
user_data = context.user_data
if user_data is None:
    return

deps = dependencies(context)
try:
    async with deps.unit_of_work() as uow:
        await GetRegisteredUser(uow.users).execute(TelegramId(update.effective_user.id))
except UserNotFoundError:
    await update.message.reply_text("Please /start first.")
    return

recommendation = await deps.verification_recommender.recommend(habit_name)
save_pending_setup(user_data, PendingHabitSetup(habit_name, recommendation))
await update.message.reply_text(format_setup_prompt(habit_name, recommendation))
```

Remove the explicit flag line from `format_help()` and delete `tests/unit/test_command_parsing.py`.

- [ ] **Step 6: Run focused tests and verify GREEN**

```bash
uv run pytest tests/unit/test_verification_setup_state.py tests/unit/test_guided_habit_setup.py tests/unit/test_checkin_flow.py tests/unit/test_formatters.py -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/habit_tracker/presentation/handlers/verification_setup.py src/habit_tracker/presentation/handlers/command_handlers.py src/habit_tracker/presentation/handlers/proof_handlers.py src/habit_tracker/presentation/formatters.py tests/unit/test_verification_setup_state.py tests/unit/test_guided_habit_setup.py tests/unit/test_checkin_flow.py tests/unit/test_formatters.py tests/unit/test_command_parsing.py
git commit -m "feat: require explicit habit verification choices"
```

---

### Task 2: Pending Setup Overlay and Phase-Aware Resume

**Files:**
- Modify: `src/habit_tracker/presentation/handlers/checkin_handlers.py:1-54`
- Modify: `src/habit_tracker/presentation/handlers/proof_handlers.py:39-211`
- Modify: `tests/unit/test_guided_habit_setup.py`
- Modify: `tests/unit/test_checkin_flow.py`
- Modify: `tests/integration/test_guided_verification_flow.py`

**Interfaces:**
- Consumes: `load_session`, `save_session`, `prepare_current_habit`, and Task 1 pending setup helpers.
- Produces: `resume_active_checkin(context, message, heading: str) -> bool`; pending setup receives text first and restores the exact session phase after success or cancellation.

- [ ] **Step 1: Write failing unit overlay tests**

In `tests/unit/test_guided_habit_setup.py`:

```python
async def test_pending_setup_pauses_checkin_and_resumes_after_choice(env) -> None:
    await CreateHabit(env.users, env.habits).execute(
        TelegramId(TELEGRAM_ID), HabitName("Gym"), verification_policy=VerificationPolicy.TEXT
    )
    await checkin_handler(update_for("/checkin"), env.context)
    await text_response_handler(update_for("yes"), env.context)
    before = dict(env.context.user_data["checkin_session"])
    await add_habit_handler(update_for("/add_habit Read"), env.context)
    reply = update_for("quiz")

    await text_response_handler(reply, env.context)

    assert env.context.user_data["checkin_session"] == before
    messages = [call.args[0] for call in reply.message.reply_text.await_args_list]
    assert messages[0] == "Habit 'Read' created with quiz verification."
    assert "Please send your text proof:" in messages[1]
```

Add the cancellation case:

```python
async def test_cancelled_setup_restores_exact_quiz_question(env) -> None:
    await CreateHabit(env.users, env.habits).execute(
        TelegramId(TELEGRAM_ID), HabitName("Learn"), verification_policy=VerificationPolicy.QUIZ
    )
    await checkin_handler(update_for("/checkin"), env.context)
    session = load_session(env.context)
    assert session is not None
    session.state = SessionState.AWAITING_QUIZ_ANSWER
    session.quiz_question = "What is await?"
    save_session(env.context, session)
    before = dict(env.context.user_data["checkin_session"])
    await add_habit_handler(update_for("/add_habit Read"), env.context)
    reply = update_for("cancel")

    await text_response_handler(reply, env.context)

    assert env.context.user_data["checkin_session"] == before
    messages = [call.args[0] for call in reply.message.reply_text.await_args_list]
    assert messages[0] == "Habit setup cancelled."
    assert "What is await?" in messages[1]
```

- [ ] **Step 2: Write the failing shared-resume phase test**

In `tests/unit/test_checkin_flow.py`, use its existing environment and session builders:

```python
@pytest.mark.parametrize(
    ("state", "quiz_question", "expected"),
    [
        (SessionState.AWAITING_RESPONSE, None, "Did you complete"),
        (SessionState.AWAITING_PROOF, None, "Please send your text proof:"),
        (SessionState.AWAITING_QUIZ_TOPIC, None, "What did you learn about today?"),
        (SessionState.AWAITING_QUIZ_ANSWER, "What is await?", "What is await?"),
    ],
)
async def test_resume_active_checkin_preserves_phase(env, state, quiz_question, expected) -> None:
    user = await _seed(env, policy=VerificationPolicy.TEXT)
    habit = (await env.habits.find_active_by_user(user.id))[0]
    session = CheckinSession.start(user_id=user.id, habits=[habit])
    session.state = state
    session.quiz_question = quiz_question
    save_session(env.context, session)
    message = SimpleNamespace(reply_text=AsyncMock())

    resumed = await resume_active_checkin(env.context, message, "Continuing your active check-in.")

    assert resumed is True
    assert expected in message.reply_text.await_args.args[0]
    assert load_session(env.context).state is state
```

- [ ] **Step 3: Write the failing repository-backed overlay test**

First change existing setup confirmations in `tests/integration/test_guided_verification_flow.py` from `"yes"` to `"photo"` and `"quiz"`; keep later ordinary check-in `"yes"` replies. Add:

```python
async def test_new_setup_pauses_repository_backed_checkin(test_session: AsyncSession) -> None:
    context = _context(test_session, VerificationPolicy.PHOTO)
    await start_handler(_update("/start"), context)
    await add_habit_handler(_update("/add_habit Gym"), context)
    await text_response_handler(_update("photo"), context)
    await checkin_handler(_update("/checkin"), context)
    await text_response_handler(_update("yes"), context)
    before = dict(context.user_data["checkin_session"])
    await add_habit_handler(_update("/add_habit Read"), context)
    choice = _update("text")

    await text_response_handler(choice, context)

    assert context.user_data["checkin_session"] == before
    replies = [call.args[0] for call in choice.message.reply_text.await_args_list]
    assert replies[0] == "Habit 'Read' created with text verification."
    assert "Please send your photo proof:" in replies[1]

    user = await SQLAlchemyUserRepository(test_session).find_by_telegram_id(TelegramId(TELEGRAM_ID))
    assert user is not None and user.id is not None
    habits = await SQLAlchemyHabitRepository(test_session).find_active_by_user(user.id)
    assert {habit.name.value: habit.verification_policy for habit in habits} == {
        "Gym": VerificationPolicy.PHOTO,
        "Read": VerificationPolicy.TEXT,
    }
```

- [ ] **Step 4: Run focused tests and verify RED**

```bash
uv run pytest tests/unit/test_guided_habit_setup.py tests/unit/test_checkin_flow.py -q
DOCKER_HOST=unix:///mnt/wsl/docker-desktop/shared-sockets/guest-services/docker.sock TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock RECORD_CASSETTES=0 uv run pytest tests/integration/test_guided_verification_flow.py -q
```

Expected: pending setup is bypassed while a check-in exists and `resume_active_checkin` is missing.

- [ ] **Step 5: Extract the shared resume helper**

In `checkin_handlers.py`, import `Message` and add:

```python
async def resume_active_checkin(
    context: ContextTypes.DEFAULT_TYPE,
    message: Message,
    heading: str,
) -> bool:
    """Repeat the exact prompt for a saved active check-in."""
    if context.user_data is None:
        return False
    session = load_session(context)
    if session is None or session.current_habit() is None:
        return False
    prompt = await prepare_current_habit(
        session,
        dependencies(context).verification_recommender,
        context.user_data,
    )
    save_session(context, session)
    await message.reply_text(f"{heading}\n\n{prompt}")
    return True
```

Replace the existing `load_session` resume block at the beginning of
`checkin_handler` with:

```python
if await resume_active_checkin(context, update.message, "You have an active check-in."):
    return
```

- [ ] **Step 6: Route pending setup first and resume when it ends**

In `proof_handlers.py`, import `resume_active_checkin`. At the beginning of `text_response_handler`:

```python
if load_pending_setup(user_data) is not None:
    await _handle_pending_habit_setup(update, context)
    return

session = load_session(context)
if session is None:
    return
```

After the cancellation reply and after a successful creation reply, call:

```python
await resume_active_checkin(context, update.message, "Continuing your active check-in.")
```

Do not resume after invalid input or failed creation because pending setup remains active.

- [ ] **Step 7: Run focused tests and verify GREEN**

```bash
uv run pytest tests/unit/test_guided_habit_setup.py tests/unit/test_checkin_flow.py tests/unit/test_verification_setup_state.py -q
DOCKER_HOST=unix:///mnt/wsl/docker-desktop/shared-sockets/guest-services/docker.sock TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock RECORD_CASSETTES=0 uv run pytest tests/integration/test_guided_verification_flow.py -q
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/habit_tracker/presentation/handlers/checkin_handlers.py src/habit_tracker/presentation/handlers/proof_handlers.py tests/unit/test_guided_habit_setup.py tests/unit/test_checkin_flow.py tests/integration/test_guided_verification_flow.py
git commit -m "feat: pause checkins for habit setup"
```

---

### Task 3: Command Interruption Lifecycle

**Files:**
- Create: `src/habit_tracker/presentation/handlers/flow_handlers.py`
- Modify: `src/habit_tracker/presentation/main.py:1-92`
- Modify: `tests/unit/test_guided_habit_setup.py`
- Modify: `tests/unit/test_wiring.py`

**Interfaces:**
- Consumes: `clear_pending_setup`, `load_pending_setup`, and Task 2 `resume_active_checkin`.
- Produces: `interrupt_pending_setup_handler`, `unknown_command_handler`, `resume_checkin_after_command_handler`, and `register_handlers(app: Application) -> None` using groups `-1`, `0`, and `1`.

- [ ] **Step 1: Write failing lifecycle tests**

Add direct-handler tests to `tests/unit/test_guided_habit_setup.py`:

```python
async def test_command_clears_setup_but_preserves_checkin(env) -> None:
    await CreateHabit(env.users, env.habits).execute(
        TelegramId(TELEGRAM_ID), HabitName("Gym"), verification_policy=VerificationPolicy.TEXT
    )
    await checkin_handler(update_for("/checkin"), env.context)
    before = dict(env.context.user_data["checkin_session"])
    await add_habit_handler(update_for("/add_habit Read"), env.context)
    command = update_for("/help")

    await interrupt_pending_setup_handler(command, env.context)

    assert "pending_habit_setup" not in env.context.user_data
    assert env.context.user_data["checkin_session"] == before
    assert command.message.reply_text.await_args.args[0] == 'Cancelled setup for "Read".'


async def test_help_result_is_followed_by_paused_checkin(env) -> None:
    await CreateHabit(env.users, env.habits).execute(
        TelegramId(TELEGRAM_ID), HabitName("Gym"), verification_policy=VerificationPolicy.TEXT
    )
    await checkin_handler(update_for("/checkin"), env.context)
    command = update_for("/help")

    await help_handler(command, env.context)
    await resume_checkin_after_command_handler(command, env.context)

    messages = [call.args[0] for call in command.message.reply_text.await_args_list]
    assert messages[0].startswith("Available commands:")
    assert "Did you complete" in messages[1]
```

Add the remaining lifecycle cases:

```python
async def test_new_add_overlay_prevents_post_command_resume(env) -> None:
    await CreateHabit(env.users, env.habits).execute(
        TelegramId(TELEGRAM_ID), HabitName("Gym"), verification_policy=VerificationPolicy.TEXT
    )
    await checkin_handler(update_for("/checkin"), env.context)
    command = update_for("/add_habit Read")

    await add_habit_handler(command, env.context)
    await resume_checkin_after_command_handler(command, env.context)

    assert command.message.reply_text.await_count == 1
    assert env.context.user_data["pending_habit_setup"]["name"] == "Read"


async def test_checkin_command_is_not_resumed_twice(env) -> None:
    await CreateHabit(env.users, env.habits).execute(
        TelegramId(TELEGRAM_ID), HabitName("Gym"), verification_policy=VerificationPolicy.TEXT
    )
    await checkin_handler(update_for("/checkin"), env.context)
    command = update_for("/checkin")

    await checkin_handler(command, env.context)
    await resume_checkin_after_command_handler(command, env.context)

    assert command.message.reply_text.await_count == 1


async def test_unknown_command_replies_then_resumes_checkin(env) -> None:
    await CreateHabit(env.users, env.habits).execute(
        TelegramId(TELEGRAM_ID), HabitName("Gym"), verification_policy=VerificationPolicy.TEXT
    )
    await checkin_handler(update_for("/checkin"), env.context)
    command = update_for("/does_not_exist")

    await unknown_command_handler(command, env.context)
    await resume_checkin_after_command_handler(command, env.context)

    messages = [call.args[0] for call in command.message.reply_text.await_args_list]
    assert messages[0] == "Unknown command. Use /help to see available commands."
    assert "Did you complete" in messages[1]
```

- [ ] **Step 2: Write the failing registration-order test**

In `tests/unit/test_wiring.py`:

```python
def test_command_lifecycle_handlers_surround_normal_commands() -> None:
    app = ApplicationBuilder().token("123:ABC").build()

    register_handlers(app)

    assert [handler.callback for handler in app.handlers[-1]] == [interrupt_pending_setup_handler]
    assert unknown_command_handler in [handler.callback for handler in app.handlers[0]]
    assert [handler.callback for handler in app.handlers[1]] == [resume_checkin_after_command_handler]
```

- [ ] **Step 3: Run focused tests and verify RED**

```bash
uv run pytest tests/unit/test_guided_habit_setup.py tests/unit/test_wiring.py -q
```

Expected: imports fail because lifecycle handlers and `register_handlers` do not exist.

- [ ] **Step 4: Implement lifecycle handlers**

Create `flow_handlers.py`:

```python
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from habit_tracker.presentation.handlers.checkin_handlers import resume_active_checkin
from habit_tracker.presentation.handlers.verification_setup import clear_pending_setup, load_pending_setup


async def interrupt_pending_setup_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancel the newest setup before another slash command runs."""
    if not update.message or context.user_data is None:
        return
    setup = load_pending_setup(context.user_data)
    if setup is None:
        return
    clear_pending_setup(context.user_data)
    await update.message.reply_text(f'Cancelled setup for "{setup.name.value}".')


async def unknown_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply to an unregistered slash command."""
    if update.message:
        await update.message.reply_text("Unknown command. Use /help to see available commands.")


async def resume_checkin_after_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Restore a paused check-in after a command finishes."""
    if not update.message or not update.message.text or context.user_data is None:
        return
    command = update.message.text.split(maxsplit=1)[0].split("@", maxsplit=1)[0].lower()
    if command == "/checkin" or load_pending_setup(context.user_data) is not None:
        return
    await resume_active_checkin(context, update.message, "Continuing your active check-in.")
```

- [ ] **Step 5: Register handlers in lifecycle groups**

In `main.py`, import `Application` and the lifecycle callbacks, then extract:

```python
def register_handlers(app: Application) -> None:
    """Register lifecycle, command, and response handlers."""
    app.add_handler(MessageHandler(filters.COMMAND, interrupt_pending_setup_handler), group=-1)
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("add_habit", add_habit_handler))
    app.add_handler(CommandHandler("list_habits", list_habits_handler))
    app.add_handler(CommandHandler("delete_habit", delete_habit_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("checkin", checkin_handler))
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_response_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_response_handler))
    app.add_handler(MessageHandler(filters.COMMAND, resume_checkin_after_command_handler), group=1)
```

Replace the inline registration block in `main()` with `register_handlers(app)`.

- [ ] **Step 6: Run focused tests and verify GREEN**

```bash
uv run pytest tests/unit/test_guided_habit_setup.py tests/unit/test_wiring.py tests/unit/test_checkin_flow.py -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/habit_tracker/presentation/handlers/flow_handlers.py src/habit_tracker/presentation/main.py tests/unit/test_guided_habit_setup.py tests/unit/test_wiring.py
git commit -m "feat: resume checkins across commands"
```

---

### Task 4: Targeted Mem0 Noise Suppression

**Files:**
- Modify: `src/habit_tracker/infrastructure/logging/logger.py:20-52`
- Modify: `tests/unit/test_logging.py:26-37`

**Interfaces:**
- Consumes: Python stdlib logger hierarchy from `configure_logging`.
- Produces: `mem0.vector_stores.pgvector` and `mem0.utils.spacy_models` at `logging.ERROR`; other Mem0 loggers unchanged.

- [ ] **Step 1: Write the failing logger-level test**

```python
def test_configure_logging_hides_routine_mem0_noise_but_keeps_errors() -> None:
    logger_names = ("mem0.vector_stores.pgvector", "mem0.utils.spacy_models")
    original_levels = {name: logging.getLogger(name).level for name in logger_names}
    unrelated = logging.getLogger("mem0.memory.main")
    unrelated_level = unrelated.level
    try:
        configure_logging()
        for name in logger_names:
            dependency_logger = logging.getLogger(name)
            assert dependency_logger.level == logging.ERROR
            assert dependency_logger.isEnabledFor(logging.WARNING) is False
            assert dependency_logger.isEnabledFor(logging.ERROR) is True
        assert unrelated.level == unrelated_level
    finally:
        for name, level in original_levels.items():
            logging.getLogger(name).setLevel(level)
        unrelated.setLevel(unrelated_level)
```

- [ ] **Step 2: Run the test and verify RED**

```bash
uv run pytest tests/unit/test_logging.py::test_configure_logging_hides_routine_mem0_noise_but_keeps_errors -q
```

Expected: both noisy loggers still inherit routine warning/info visibility.

- [ ] **Step 3: Configure only the two noisy namespaces**

After HTTP client configuration in `configure_logging`:

```python
for logger_name in ("mem0.vector_stores.pgvector", "mem0.utils.spacy_models"):
    logging.getLogger(logger_name).setLevel(logging.ERROR)
```

- [ ] **Step 4: Run logging tests and verify GREEN**

```bash
uv run pytest tests/unit/test_logging.py -q
```

Expected: all logging and secret-redaction tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/habit_tracker/infrastructure/logging/logger.py tests/unit/test_logging.py
git commit -m "fix: suppress routine mem0 fallback logs"
```

---

### Task 5: Full Static and Runtime Verification

**Files:**
- Verify only; no planned production changes.

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: branch-level evidence for review and integration.

- [ ] **Step 1: Run all unit tests**

```bash
uv run pytest tests/unit -q
```

Expected: all unit tests pass.

- [ ] **Step 2: Run formatting, lint, and type gates**

```bash
uv run ruff format --check src tests
uv run ruff check src tests
uvx --from pyrefly pyrefly check src --ignore bad-override,missing-import,not-callable --output-format omit-errors
```

Expected: formatted files, clean lint, and zero Pyrefly errors.

- [ ] **Step 3: Run the complete integration suite with Ryuk enabled**

```bash
DOCKER_HOST=unix:///mnt/wsl/docker-desktop/shared-sockets/guest-services/docker.sock TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock RECORD_CASSETTES=0 uv run pytest tests/integration -q
```

Expected: all integrations pass without Testcontainers setup errors.

- [ ] **Step 4: Run the exact project test recipe**

```bash
DOCKER_HOST=unix:///mnt/wsl/docker-desktop/shared-sockets/guest-services/docker.sock TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock RECORD_CASSETTES=0 just test
```

Expected: the complete parallel suite passes and Ryuk sidecars remove themselves after their reconnection grace period.

- [ ] **Step 5: Inspect the final branch**

```bash
git diff --check main...HEAD
git status --short
git log --oneline main..HEAD
```

Expected: clean diff check, clean worktree, and only intentional feature commits.
