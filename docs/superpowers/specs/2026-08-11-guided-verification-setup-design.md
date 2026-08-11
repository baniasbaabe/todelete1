# Guided Verification Setup Design

## Goal

Make every habit's verification behavior deliberate and visible. When a user
creates a habit without an explicit verification policy, the bot recommends a
policy, asks the user to confirm or replace it, and saves the habit only after
that choice. Existing habits whose policy is `none` receive the same one-time
setup during their next check-in.

## Current Behavior and Root Cause

`/add_habit <name>` currently defaults to `VerificationPolicy.NONE`. During a
check-in, a `none` habit is completed immediately after the user replies
`yes`, so the bot advances to the next habit without asking for evidence.

The proof flows themselves already exist:

- `photo` requests an image and verifies it.
- `quiz` asks what the user learned, generates a question, and evaluates the
  answer.
- `text` requests written proof and verifies it.
- `none` records completion without further verification.

The missing part is a guided way to select a policy and to repair existing
habits that use the default.

## User Experience

### New Habits

For `/add_habit Gym`, the bot does not create the habit immediately. It asks:

```text
For "Gym", I recommend photo verification.
Reply yes to use it, or choose: photo, quiz, text, none.
Reply cancel to stop.
```

For `/add_habit Learn Python`, the recommended policy is `quiz`.

The accepted responses are case-insensitive:

- `yes` selects the recommendation.
- `photo`, `quiz`, `text`, or `none` selects that exact policy.
- `cancel` discards the pending habit.
- Any other text repeats the available choices without creating a habit.

The existing explicit form remains backward compatible and bypasses the
guided setup:

```text
/add_habit Gym --verify photo
/add_habit Learn Python --verify quiz
```

Only one pending habit setup may exist per user. Starting another
`/add_habit` replaces the pending setup and clearly tells the user which habit
is now being configured.

### Existing Habits

When check-in reaches an existing habit with policy `none`, the bot pauses
before asking whether it was completed and displays the same recommendation
and choices. The selected policy is persisted on the existing habit. The bot
then asks the normal check-in question for that policy.

If the user selects `none`, that is treated as an explicit choice. The bot asks
the normal yes/skip question and does not prompt for configuration again.
This requires distinguishing an old implicit default from a confirmed `none`
choice.

To avoid a database migration solely for this distinction, confirmed policy
setup is tracked using the existing persisted Telegram `user_data`, keyed by
habit ID. A habit with a non-`none` policy is always considered configured. A
`none` habit is configured only when its ID is present in that set. If the
state is ever lost, the worst outcome is one additional confirmation prompt;
habit data remains correct.

## Recommendation Strategy

The bot uses an AI-backed recommender because it can understand habit names
beyond a fixed keyword list. The model must return one of the four supported
enum values: `photo`, `quiz`, `text`, or `none`.

The prompt describes the intended meanings:

- `photo`: an activity or result that can reasonably be shown in an image.
- `quiz`: learning, studying, reading, courses, languages, or skills that can
  be checked with a question.
- `text`: evidence is best explained in writing.
- `none`: verification would be intrusive, meaningless, or impractical.

The recommender never makes the final choice. The user must confirm or replace
the suggestion.

If the model call fails, times out, returns malformed data, or returns an
unknown value, a deterministic keyword fallback is used:

- Learning terms such as `learn`, `study`, `read`, `course`, `practice`,
  language names, and programming names recommend `quiz`.
- Observable exercise terms such as `gym`, `workout`, `run`, `walk`, `cycle`,
  `yoga`, and `swim` recommend `photo`.
- All other names recommend `text`.

`none` is not selected by the deterministic fallback; it remains available as
an explicit user choice.

The recommendation call uses the existing `LLMClient` abstraction and its
structured-output path. Groq reasoning remains disabled as already configured,
and no reasoning text is shown to the user.

## Architecture

### Application Layer

Add a `VerificationRecommender` service interface with:

```python
async def recommend(self, habit_name: HabitName) -> VerificationPolicy: ...
```

Add an application service that implements the deterministic fallback and
wraps the AI implementation so callers always receive a valid policy.

Add a `SetHabitVerification` use case for existing habits. It locates an active
habit owned by the Telegram user, changes its policy, and saves it through the
repository. Ownership validation remains in the application layer.

### Infrastructure Layer

Add an LLM-backed implementation of `VerificationRecommender`. It requests a
single structured enum value and converts it to `VerificationPolicy`. It does
not expose model-generated explanation or reasoning.

### Presentation Layer

Store pending creation state in persisted `context.user_data` as plain JSON
data containing the habit name and recommended policy. Do not store domain
objects or service instances in persisted Telegram state.

Store the IDs of explicitly configured `none` habits in the same persisted
user data.

Text routing follows this priority:

1. Active check-in state, including verification setup for an existing habit.
2. Pending new-habit setup.
3. Ignore ordinary text that is unrelated to either flow.

This prevents a creation response from being consumed as check-in proof and
prevents an active check-in response from accidentally creating a habit.

The `/add_habit` command handler continues to create explicit `--verify`
habits immediately. Without `--verify`, it obtains a recommendation, saves the
pending setup, and asks for confirmation.

Check-in startup and habit advancement call a common prompt formatter. If the
current habit needs one-time setup, the formatter returns the setup prompt;
otherwise it returns the existing yes/skip prompt. After setup, the current
habit remains selected and the bot asks its normal completion question; the
session must not advance.

## Error Handling

- Recommendation failures are logged and use the deterministic fallback.
- Creation failures leave no half-created habit. The pending state is cleared
  only after successful creation or explicit cancellation.
- Existing-habit update failures keep the check-in on the same habit and return
  a user-friendly retry message.
- Duplicate habit errors are reported when the final creation is attempted.
- Commands remain routable while a setup is pending.

## Testing

Unit tests cover:

- AI enum parsing and rejection of malformed output.
- Deterministic fallback categories, including `Gym` -> `photo` and
  `Learn Python` -> `quiz`.
- `/add_habit` without `--verify` creates pending state but no database habit.
- `yes`, explicit policy, invalid input, and `cancel` responses.
- Explicit `--verify` remains immediate and backward compatible.
- Existing `none` habits pause for one-time setup.
- Selecting a policy updates the habit without advancing the check-in.
- Selecting explicit `none` does not prompt again.
- Quiz and photo flows continue after setup.
- Setup state survives Telegram persistence refresh.
- A check-in takes routing priority over pending habit creation.

Integration tests cover one complete guided creation followed by check-in for
both `photo` and `quiz` policies. Existing check-in regression tests continue
to verify that yes/skip advances exactly once.

## Non-Goals

- No database schema changes.
- No automatic proof policy changes after the user confirms a choice.
- No free-form model reasoning is shown to the user.
- No generated quiz answer is accepted without evaluation.
- No changes to streak calculation or completion semantics.
