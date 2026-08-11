"""Guided verification choice through the real Telegram text handlers."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.ext import ApplicationBuilder

from habit_tracker.application.use_cases.create_habit import CreateHabit
from habit_tracker.application.use_cases.register_user import RegisterUser
from habit_tracker.domain.value_objects import HabitName, TelegramId
from habit_tracker.domain.value_objects.verification_policy import VerificationPolicy
from habit_tracker.infrastructure.database.unit_of_work import UnitOfWork
from habit_tracker.presentation.dependencies import Dependencies, install
from habit_tracker.presentation.handlers.checkin_handlers import checkin_handler
from habit_tracker.presentation.handlers.command_handlers import add_habit_handler
from habit_tracker.presentation.handlers.proof_handlers import text_response_handler
from tests.unit.conftest import (
    FakeMemoryStore,
    FakePatternAnalyzer,
    FakeProofVerifier,
    FakeVerificationRecommender,
    InMemoryCompletionRepository,
    InMemoryHabitRepository,
    InMemoryUserRepository,
)

TELEGRAM_ID = 246810


class _InMemoryDependencies(Dependencies):
    """Dependencies whose unit of work uses in-memory repositories."""

    def __init__(self, users, habits, completions, **kwargs) -> None:
        super().__init__(db=SimpleNamespace(), **kwargs)
        object.__setattr__(self, "_repos", (users, habits, completions))

    @asynccontextmanager
    async def unit_of_work(self):
        users, habits, completions = self._repos
        yield UnitOfWork(
            users=users,
            habits=habits,
            completions=completions,
            session=SimpleNamespace(commit=AsyncMock()),
        )


@pytest.fixture
async def env():
    users = InMemoryUserRepository()
    habits = InMemoryHabitRepository()
    completions = InMemoryCompletionRepository()
    recommender = FakeVerificationRecommender(VerificationPolicy.PHOTO)
    deps = _InMemoryDependencies(
        users,
        habits,
        completions,
        proof_verifier=FakeProofVerifier(),
        memory_store=FakeMemoryStore(),
        pattern_analyzer=FakePatternAnalyzer(),
        verification_recommender=recommender,
    )
    app = ApplicationBuilder().token("123:ABC").build()
    install(app, deps)
    user, _ = await RegisterUser(users).execute(TelegramId(TELEGRAM_ID))
    context = SimpleNamespace(application=app, user_data={}, bot=None)
    return SimpleNamespace(
        users=users,
        habits=habits,
        completions=completions,
        recommender=recommender,
        user=user,
        context=context,
    )


def update_for(text: str) -> SimpleNamespace:
    message = SimpleNamespace(text=text, reply_text=AsyncMock(), photo=[])
    return SimpleNamespace(message=message, effective_user=SimpleNamespace(id=TELEGRAM_ID, username="tester"))


async def test_add_without_verify_waits_for_confirmation(env) -> None:
    command = update_for("/add_habit Gym")

    await add_habit_handler(command, env.context)

    assert await env.habits.find_active_by_user(env.user.id) == []
    assert env.context.user_data["pending_habit_setup"] == {
        "name": "Gym",
        "recommendation": "photo",
    }
    assert "recommend photo" in command.message.reply_text.await_args.args[0].lower()
    assert env.recommender.names == ["Gym"]


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


async def test_cancel_clears_pending_setup(env) -> None:
    await add_habit_handler(update_for("/add_habit Gym"), env.context)
    reply = update_for("cancel")

    await text_response_handler(reply, env.context)

    assert "pending_habit_setup" not in env.context.user_data
    assert reply.message.reply_text.await_args.args[0] == "Habit setup cancelled."


async def test_invalid_choice_repeats_prompt_and_keeps_pending_setup(env) -> None:
    await add_habit_handler(update_for("/add_habit Gym"), env.context)
    reply = update_for("maybe")

    await text_response_handler(reply, env.context)

    assert env.context.user_data["pending_habit_setup"]["name"] == "Gym"
    assert "recommend photo" in reply.message.reply_text.await_args.args[0].lower()


async def test_duplicate_failure_keeps_pending_setup(env) -> None:
    await CreateHabit(env.users, env.habits).execute(TelegramId(TELEGRAM_ID), HabitName("Gym"))
    await add_habit_handler(update_for("/add_habit Gym"), env.context)
    reply = update_for("yes")

    await text_response_handler(reply, env.context)

    assert env.context.user_data["pending_habit_setup"]["name"] == "Gym"
    assert reply.message.reply_text.await_args.args[0] == "That habit already exists!"


async def test_choice_is_case_insensitive(env) -> None:
    await add_habit_handler(update_for("/add_habit Journal"), env.context)

    await text_response_handler(update_for("  TeXT  "), env.context)

    habit = (await env.habits.find_active_by_user(env.user.id))[0]
    assert habit.verification_policy is VerificationPolicy.TEXT


async def test_second_setup_replaces_the_first(env) -> None:
    await add_habit_handler(update_for("/add_habit Gym"), env.context)
    replacement = update_for("/add_habit Read")

    await add_habit_handler(replacement, env.context)

    assert env.context.user_data["pending_habit_setup"]["name"] == "Read"
    assert replacement.message.reply_text.await_args.args[0].startswith('Replacing the pending setup with "Read".')


async def test_explicit_none_marks_the_new_habit_as_configured(env) -> None:
    await add_habit_handler(update_for("/add_habit Rest"), env.context)

    await text_response_handler(update_for("none"), env.context)

    habit = (await env.habits.find_active_by_user(env.user.id))[0]
    assert habit.verification_policy is VerificationPolicy.NONE
    assert env.context.user_data["configured_none_habit_ids"] == [habit.id]


async def test_explicit_verify_bypasses_recommender_and_creates_immediately(env) -> None:
    command = update_for("/add_habit Gym --verify photo")

    await add_habit_handler(command, env.context)

    habit = (await env.habits.find_active_by_user(env.user.id))[0]
    assert habit.verification_policy is VerificationPolicy.PHOTO
    assert "pending_habit_setup" not in env.context.user_data
    assert env.recommender.names == []
    assert "created" in command.message.reply_text.await_args.args[0].lower()


async def test_active_checkin_handles_text_before_pending_setup(env) -> None:
    await CreateHabit(env.users, env.habits).execute(
        TelegramId(TELEGRAM_ID),
        HabitName("Gym"),
        verification_policy=VerificationPolicy.TEXT,
    )
    await add_habit_handler(update_for("/add_habit Read"), env.context)
    await checkin_handler(update_for("/checkin"), env.context)
    reply = update_for("maybe")

    await text_response_handler(reply, env.context)

    assert "checkin_session" in env.context.user_data
    assert env.context.user_data["pending_habit_setup"]["name"] == "Read"
    assert "didn't catch that" in reply.message.reply_text.await_args.args[0].lower()
