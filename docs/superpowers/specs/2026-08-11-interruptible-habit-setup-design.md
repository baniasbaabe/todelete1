# Interruptible Habit Setup Design

## Context

Habit creation currently supports an optional `--verify` flag and otherwise
starts a guided verification setup. The flag is fragile in chat input, exposes
parser details to users, and can accidentally become part of a habit name.
Pending habit setup also conflicts with an active check-in because ordinary
text is routed to the check-in before the newer setup flow.

Mem0 additionally emits routine PostgreSQL, vector insertion, and optional
spaCy warnings during successful memory writes. The application intentionally
uses Mem0's lightweight fallback without spaCy, so those messages add noise
without identifying an application failure.

There are no existing users, so the revised command requires no compatibility
path for verification flags or the old `yes` setup response.

## Goals

- Make `/add_habit <name>` the only habit creation syntax.
- Recommend a verification policy and require an explicit policy choice.
- Let a newer habit setup temporarily pause an active check-in and resume it
  at the exact phase afterward.
- Let slash commands interrupt pending habit setup without destroying an
  active check-in.
- Keep genuine Mem0 failures visible while hiding known routine library noise.

## Non-Goals

- Supporting or rejecting legacy `--verify` syntax specially.
- Adding Telegram callback buttons or a new conversation framework.
- Cancelling a check-in when another command runs.
- Installing spaCy or downloading a language model at runtime.
- Changing Mem0 persistence, embeddings, or retrieval behavior.

## Habit Creation Interaction

`/add_habit` treats all text after the command as the habit name. It has no
verification flag parser, flag validation, or compatibility behavior. Help and
usage text advertise only `/add_habit <name>`.

After validating that the user is registered, the handler obtains a safe AI
recommendation and stores a JSON-safe pending setup. The prompt uses this form:

```text
For "Learning Python", I recommend quiz verification.
Choose: quiz, photo, text, or none.
Reply 'cancel' to stop.
```

The only accepted setup inputs are `quiz`, `photo`, `text`, `none`, and
`cancel`, matched case-insensitively after trimming whitespace. `yes` is not a
valid choice. An invalid choice repeats the prompt and does not create a habit.

The existing recommendation fallback remains unchanged:

- learning habits recommend quiz;
- gym and exercise habits recommend photo;
- other habits recommend text.

The selected policy is persisted only when the habit is created successfully.
Failed creation retains the pending setup so the user can retry or cancel.

## Flow Priority and Interruption

An active check-in is the base flow. A pending habit setup is a temporary
overlay above it. Ordinary text is routed to the newest flow:

1. pending habit setup, when present;
2. otherwise, the active check-in;
3. otherwise, no stateful response handler.

Completing or cancelling the overlay removes it. If a check-in is paused, the
bot immediately repeats the exact current check-in prompt. This uses the
existing phase-aware prompt preparation, so photo proof, quiz topic, quiz
answer, verification setup, and ordinary yes/skip phases resume correctly.

A pre-command handler runs before command-specific handlers. Any slash command
clears a pending habit setup and reports which setup was cancelled. The command
then executes normally. The saved check-in is never cleared by this step.

A post-command handler then restores the current check-in prompt when a
check-in exists and no newer habit setup is pending. It skips `/checkin`, whose
handler already restores the prompt. This ordering lets the requested command
show its normal result before the paused question is repeated. Consequently:

- `/checkin` resumes the saved check-in;
- `/add_habit` replaces the cancelled overlay with a new setup while leaving
  the check-in paused;
- single-step commands such as `/help` and `/list_habits` run without losing
  check-in progress, then repeat the paused check-in question;
- an unknown slash command receives a short unknown-command response instead
  of silently consuming the interruption, then repeats the paused question.

## Components

### Command handlers

The add-habit handler extracts a `HabitName` directly from the command tail,
checks registration, obtains a recommendation, stores pending setup, and sends
the choice prompt. The explicit-policy immediate creation path is removed.

A small pre-command handler owns interruption of pending habit setup. It is
registered in an earlier Telegram handler group so it runs before all known
and unknown command handlers without duplicating cleanup across commands.

An unknown-command handler is registered after known command handlers. A
post-command handler in a later group resumes a saved check-in after the
requested command unless `/checkin` already resumed it or `/add_habit` created
a newer setup overlay.

### Stateful text routing

The text response handler checks pending habit setup before loading a check-in
session. After setup completion or cancellation, a shared resume helper formats
and persists the paused check-in prompt when one exists.

The setup choice parser maps only explicit verification policy values. It no
longer maps `yes` to the recommendation.

### Logging configuration

Application logging raises only the noisy Mem0 logger namespaces to `ERROR`:

- `mem0.vector_stores.pgvector`, which emits connection-pool and insertion
  status at `INFO`;
- `mem0.utils.spacy_models`, which warns when the intentionally optional spaCy
  model is unavailable.

This retains `ERROR` and `CRITICAL` records from those modules and does not
silence other Mem0 warnings. Mem0 continues its documented fallback: original
text for BM25 processing and no extracted entities when spaCy is unavailable.

## Error Handling

- Missing or blank habit names return the simplified add-habit usage message.
- Unregistered users are told to run `/start` before recommendation work.
- Invalid setup choices repeat the choice prompt without changing state.
- Duplicate or invalid habit creation reports the existing user-facing error
  and retains pending setup.
- A malformed persisted pending setup is discarded by the existing loader.
- Recommendation failures continue to use the bounded deterministic fallback.
- Unknown commands report that the command is unavailable after interruption
  cleanup has run.

## Testing

Focused tests will prove these contracts before production changes:

- `/add_habit Learning Python` stores pending setup and displays an explicit
  recommendation and policy choices;
- help and usage text contain no verification flag syntax;
- `yes` is invalid while every supported policy creates the correct habit;
- pending setup receives ordinary text before an active check-in;
- completion and cancellation restore the exact paused check-in phase;
- every slash command clears pending setup but preserves serialized check-in
  state, and known commands still run;
- single-step and unknown commands respond before the exact check-in prompt is
  repeated;
- `/add_habit` keeps the check-in paused behind its new setup, while `/checkin`
  resumes only once;
- routine Mem0/spaCy messages are filtered while errors remain loggable.

After focused red/green cycles, verification runs the complete unit suite,
Ruff formatting and linting, Pyrefly, and the Docker-backed integration suite
with Testcontainers Ryuk enabled.
