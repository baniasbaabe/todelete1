from __future__ import annotations

from telegram import Message, Update
from telegram.ext import ContextTypes

from habit_tracker.application.checkin_session import CheckinSession, SessionState
from habit_tracker.application.use_cases.record_checkin_insight import RecordCheckinInsight
from habit_tracker.application.use_cases.verify_and_complete import VerifyAndComplete, VerifyAndCompleteResult
from habit_tracker.domain.value_objects.verification_policy import VerificationPolicy
from habit_tracker.infrastructure.observability.tracing import trace
from habit_tracker.presentation.dependencies import dependencies
from habit_tracker.presentation.formatters import format_checkin_prompt, format_checkin_summary
from habit_tracker.presentation.handlers.session_store import clear_session, load_session, save_session

AFFIRMATIVE = ("yes", "y", "done", "completed")
NEGATIVE = ("no", "n")


def _record_insight(session: CheckinSession, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Write the finished session to long-term memory without blocking the reply.

    mem0 does embedding work on write, so awaiting it here would stall the
    user's last check-in message behind a network round trip. ``create_task``
    hands it to the Application, which awaits outstanding tasks on shutdown.
    """
    deps = dependencies(context)
    context.application.create_task(
        RecordCheckinInsight(deps.memory_store).execute(
            session.user_id,
            session.results,
            session.created_at,
        )
    )


async def _advance_and_reply(
    session: CheckinSession,
    context: ContextTypes.DEFAULT_TYPE,
    message: Message,
    label: str,
) -> None:
    """Move past the current habit, persist session state, and reply."""
    next_habit = session.advance()

    if next_habit is None:
        clear_session(context)
        _record_insight(session, context)
        await message.reply_text(f"{label}\n\n{format_checkin_summary(session.get_summary())}")
        return

    save_session(context, session)
    await message.reply_text(f"{label}\n\n{format_checkin_prompt(next_habit)}")


async def _advance_after_verification(
    session: CheckinSession,
    result: VerifyAndCompleteResult,
    context: ContextTypes.DEFAULT_TYPE,
    message: Message,
    prefix: str,
) -> None:
    """Record a verification outcome, then advance."""
    if result.verified:
        session.record_completion()
        streak_msg = f" (streak: {result.streak.current})" if result.streak else ""
        label = f"{prefix}{streak_msg}"
    else:
        reasoning = result.proof_result.reasoning if result.proof_result else "Unknown"
        session.record_skip()
        label = f"Not verified: {reasoning}"

    await _advance_and_reply(session, context, message, label)


@trace("text_response", handler="text_response")
async def text_response_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text responses during check-in."""
    if not update.message or not update.effective_user or update.message.text is None:
        return

    session = load_session(context)
    if session is None:
        return  # Not in a check-in

    habit = session.current_habit()
    if not habit:
        return

    text = update.message.text.strip().lower()

    if text == "skip":
        session.record_skip()
        await _advance_and_reply(session, context, update.message, "Skipped.")
        return

    deps = dependencies(context)

    if session.state == SessionState.AWAITING_PROOF:
        async with deps.unit_of_work() as uow:
            verify = VerifyAndComplete(uow.completions, deps.proof_verifier)
            result = await verify.execute(habit, proof_text=update.message.text)
            await uow.commit()
        await _advance_after_verification(session, result, context, update.message, "Verified!")
        return

    if session.state == SessionState.AWAITING_QUIZ_TOPIC:
        question = await deps.proof_verifier.generate_quiz(habit, update.message.text)
        session.state = SessionState.AWAITING_QUIZ_ANSWER
        session.quiz_question = question
        save_session(context, session)
        await update.message.reply_text(f"Quick quiz time!\n\n{question}")
        return

    if session.state == SessionState.AWAITING_QUIZ_ANSWER:
        async with deps.unit_of_work() as uow:
            verify = VerifyAndComplete(uow.completions, deps.proof_verifier)
            result = await verify.execute(
                habit,
                proof_text=update.message.text,
                quiz_question=session.quiz_question,
            )
            await uow.commit()
        session.quiz_question = None
        await _advance_after_verification(session, result, context, update.message, "Quiz checked!")
        return

    if text in NEGATIVE:
        session.record_skip()
        await _advance_and_reply(session, context, update.message, "Okay.")
        return

    if text in AFFIRMATIVE:
        if habit.verification_policy == VerificationPolicy.QUIZ:
            session.state = SessionState.AWAITING_QUIZ_TOPIC
            save_session(context, session)
            await update.message.reply_text("Nice! What did you learn about today?")
            return

        if habit.requires_proof():
            session.state = SessionState.AWAITING_PROOF
            save_session(context, session)
            await update.message.reply_text(f"Please send your {habit.verification_policy.value} proof:")
            return

        async with deps.unit_of_work() as uow:
            verify = VerifyAndComplete(uow.completions, deps.proof_verifier)
            result = await verify.execute(habit)
            await uow.commit()
        await _advance_after_verification(session, result, context, update.message, "Done!")
        return

    await update.message.reply_text(f"I didn't catch that.\n\n{format_checkin_prompt(habit)}")


@trace("photo_response", handler="photo_response")
async def photo_response_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle photo proof during check-in."""
    if not update.message or not update.effective_user:
        return

    session = load_session(context)
    if session is None or session.state != SessionState.AWAITING_PROOF:
        return

    habit = session.current_habit()
    if not habit:
        return

    deps = dependencies(context)
    photo = update.message.photo[-1]  # Largest resolution
    file = await context.bot.get_file(photo.file_id)
    image_bytes = await file.download_as_bytearray()

    async with deps.unit_of_work() as uow:
        verify = VerifyAndComplete(uow.completions, deps.proof_verifier)
        result = await verify.execute(habit, image_bytes=bytes(image_bytes))
        await uow.commit()

    await _advance_after_verification(session, result, context, update.message, "Photo verified!")
