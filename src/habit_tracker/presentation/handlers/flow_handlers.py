from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from habit_tracker.presentation.handlers.checkin_handlers import resume_active_checkin
from habit_tracker.presentation.handlers.verification_setup import (
    clear_pending_setup,
    load_pending_setup,
)


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
