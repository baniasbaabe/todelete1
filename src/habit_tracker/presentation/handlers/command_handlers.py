from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from habit_tracker.application.use_cases.delete_habit import DeleteHabit
from habit_tracker.application.use_cases.get_registered_user import GetRegisteredUser
from habit_tracker.application.use_cases.list_habits import ListHabits
from habit_tracker.application.use_cases.register_user import RegisterUser
from habit_tracker.domain.exceptions import (
    HabitNotFoundError,
    UserNotFoundError,
)
from habit_tracker.domain.value_objects import HabitName, TelegramId
from habit_tracker.infrastructure.observability.tracing import trace
from habit_tracker.presentation.dependencies import dependencies
from habit_tracker.presentation.formatters import format_habit_list, format_help
from habit_tracker.presentation.handlers.verification_setup import (
    PendingHabitSetup,
    format_setup_prompt,
    save_pending_setup,
)

_ADD_HABIT_USAGE = "Usage: /add_habit <name>"


@trace("start", handler="start")
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    async with dependencies(context).unit_of_work() as uow:
        register = RegisterUser(uow.users)
        _, is_new = await register.execute(
            TelegramId(update.effective_user.id),
            update.effective_user.username,
        )
        await uow.commit()
    msg = "Welcome! You're all set." if is_new else "Welcome back!"
    await update.message.reply_text(f"{msg}\n\n{format_help()}")


@trace("add_habit", handler="add_habit")
async def add_habit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user or not update.message.text:
        return
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


@trace("list_habits", handler="list_habits")
async def list_habits_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    try:
        async with dependencies(context).unit_of_work() as uow:
            list_uc = ListHabits(uow.users, uow.habits, uow.completions)
            results = await list_uc.execute(TelegramId(update.effective_user.id))
        habits = [r[0] for r in results]
        streaks = [r[1] for r in results]
        await update.message.reply_text(format_habit_list(habits, streaks))
    except UserNotFoundError:
        await update.message.reply_text("Please /start first.")


@trace("delete_habit", handler="delete_habit")
async def delete_habit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user or not update.message.text:
        return
    args = update.message.text.split(maxsplit=1)
    if len(args) < 2:
        await update.message.reply_text("Usage: /delete_habit <name>")
        return
    try:
        async with dependencies(context).unit_of_work() as uow:
            delete = DeleteHabit(uow.users, uow.habits)
            await delete.execute(TelegramId(update.effective_user.id), HabitName(args[1]))
            await uow.commit()
        await update.message.reply_text(f"Habit '{args[1]}' deleted.")
    except UserNotFoundError:
        await update.message.reply_text("Please /start first.")
    except HabitNotFoundError:
        await update.message.reply_text("Habit not found.")


@trace("help", handler="help")
async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    await update.message.reply_text(format_help())
