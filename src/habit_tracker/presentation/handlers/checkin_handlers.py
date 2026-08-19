from __future__ import annotations

from telegram import Message, Update
from telegram.ext import ContextTypes

from habit_tracker.application.checkin_session import CheckinSession
from habit_tracker.application.use_cases.start_checkin import StartCheckin
from habit_tracker.domain.exceptions import UserNotFoundError
from habit_tracker.domain.value_objects import TelegramId
from habit_tracker.infrastructure.observability.tracing import trace
from habit_tracker.presentation.dependencies import dependencies
from habit_tracker.presentation.handlers.session_store import load_session, save_session
from habit_tracker.presentation.handlers.verification_setup import prepare_current_habit


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


@trace("checkin", save_context=True, handler="checkin")
async def checkin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start a check-in session."""
    if not update.message or not update.effective_user or context.user_data is None:
        return
    deps = dependencies(context)
    user_data = context.user_data

    if await resume_active_checkin(context, update.message, "You have an active check-in."):
        return

    try:
        async with deps.unit_of_work() as uow:
            start = StartCheckin(uow.users, uow.habits, uow.completions, deps.pattern_analyzer)
            result = await start.execute(TelegramId(update.effective_user.id))

        if not result.pending:
            await update.message.reply_text(result.coaching)
            return

        # The persistent user ID, not the Telegram ID: the session's insights are
        # written and read back under it.
        session = CheckinSession.start(
            user_id=result.user_id,
            habits=result.pending,
        )
        prompt = await prepare_current_habit(session, deps.verification_recommender, user_data)
        save_session(context, session)

        await update.message.reply_text(f"{result.coaching}\n\n{prompt}")

    except UserNotFoundError:
        await update.message.reply_text("Please /start first.")
