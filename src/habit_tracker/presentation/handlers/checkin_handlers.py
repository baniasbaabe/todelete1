from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from habit_tracker.application.checkin_session import CheckinSession
from habit_tracker.application.use_cases.start_checkin import StartCheckin
from habit_tracker.domain.exceptions import UserNotFoundError
from habit_tracker.domain.value_objects import TelegramId
from habit_tracker.infrastructure.observability.tracing import trace
from habit_tracker.presentation.dependencies import dependencies
from habit_tracker.presentation.formatters import format_checkin_prompt
from habit_tracker.presentation.handlers.session_store import load_session, save_session


@trace("checkin", handler="checkin")
async def checkin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start a check-in session."""
    if not update.message or not update.effective_user:
        return
    deps = dependencies(context)

    existing = load_session(context)
    if existing:
        habit = existing.current_habit()
        if habit:
            await update.message.reply_text(f"You have an active check-in.\n\n{format_checkin_prompt(habit)}")
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
        save_session(context, session)

        await update.message.reply_text(f"{result.coaching}\n\n{format_checkin_prompt(result.pending[0])}")

    except UserNotFoundError:
        await update.message.reply_text("Please /start first.")
