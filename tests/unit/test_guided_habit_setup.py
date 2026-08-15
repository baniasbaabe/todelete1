"""Guided verification choice through the real Telegram text handlers."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.ext import ApplicationBuilder

from habit_tracker.application.checkin_session import SessionState
from habit_tracker.application.use_cases.create_habit import CreateHabit
from habit_tracker.application.use_cases.register_user import RegisterUser
from habit_tracker.domain.value_objects import HabitName, TelegramId
from habit_tracker.domain.value_objects.verification_policy import VerificationPolicy
from habit_tracker.infrastructure.database.unit_of_work import UnitOfWork
from habit_tracker.presentation.dependencies import Dependencies, install
from habit_tracker.presentation.handlers.checkin_handlers import checkin_handler
from habit_tracker.presentation.handlers.command_handlers import add_habit_handler, help_handler
from habit_tracker.presentation.handlers.flow_handlers import (
    interrupt_pending_setup_handler,
    resume_checkin_after_command_handler,
    unknown_command_handler,
)
from habit_tracker.presentation.handlers.proof_handlers import text_response_handler
from habit_tracker.presentation.handlers.session_store import load_session, save_session
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
        object.__setattr__(self, "uow_session", SimpleNamespace(commit=AsyncMock()))

    @asynccontextmanager
    async def unit_of_work(self):
        users, habits, completions = self._repos
        yield UnitOfWork(
            users=users,
            habits=habits,
            completions=completions,
            session=self.uow_session,
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
        uow_session=deps.uow_session,
        context=context,
    )


def update_for(text: str, *, telegram_id: int = TELEGRAM_ID) -> SimpleNamespace:
    message = SimpleNamespace(text=text, reply_text=AsyncMock(), photo=[])
    return SimpleNamespace(message=message, effective_user=SimpleNamespace(id=telegram_id, username="tester"))


async def test_add_habit_always_waits_for_explicit_choice(env) -> None:
    command = update_for("/add_habit Gym")

    await add_habit_handler(command, env.context)

    assert await env.habits.find_active_by_user(env.user.id) == []
    assert env.context.user_data["pending_habit_setup"] == {
        "name": "Gym",
        "recommendation": "photo",
    }
    prompt = command.message.reply_text.await_args.args[0]
    assert "Choose: quiz, photo, text, or none." in prompt
    assert "yes" not in prompt.lower()
    assert env.recommender.names == ["Gym"]


async def test_add_without_user_data_is_ignored(env) -> None:
    env.context.user_data = None

    await add_habit_handler(update_for("/add_habit Gym"), env.context)

    assert await env.habits.find_active_by_user(env.user.id) == []
    assert env.recommender.names == []


async def test_unregistered_user_is_rejected_before_recommendation(env) -> None:
    command = update_for("/add_habit Gym", telegram_id=TELEGRAM_ID + 1)

    await add_habit_handler(command, env.context)

    assert env.recommender.names == []
    assert "pending_habit_setup" not in env.context.user_data
    assert command.message.reply_text.await_args.args[0] == "Please /start first."


async def test_yes_repeats_prompt_without_creating(env) -> None:
    await add_habit_handler(update_for("/add_habit Gym"), env.context)
    reply = update_for("yes")

    await text_response_handler(reply, env.context)

    assert await env.habits.find_active_by_user(env.user.id) == []
    assert env.context.user_data["pending_habit_setup"]["name"] == "Gym"
    assert "Choose: quiz, photo, text, or none." in reply.message.reply_text.await_args.args[0]


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
    assert "Choose: quiz, photo, text, or none." in reply.message.reply_text.await_args.args[0]


async def test_duplicate_failure_keeps_pending_setup(env) -> None:
    await CreateHabit(env.users, env.habits).execute(TelegramId(TELEGRAM_ID), HabitName("Gym"))
    await add_habit_handler(update_for("/add_habit Gym"), env.context)
    reply = update_for("photo")

    await text_response_handler(reply, env.context)

    assert env.context.user_data["pending_habit_setup"]["name"] == "Gym"
    assert reply.message.reply_text.await_args.args[0] == "That habit already exists!"


async def test_choice_is_case_insensitive(env) -> None:
    await add_habit_handler(update_for("/add_habit Journal"), env.context)

    await text_response_handler(update_for("  TeXT  "), env.context)

    habit = (await env.habits.find_active_by_user(env.user.id))[0]
    assert habit.verification_policy is VerificationPolicy.TEXT


async def test_second_add_replaces_pending_state(env) -> None:
    await add_habit_handler(update_for("/add_habit Gym"), env.context)

    await add_habit_handler(update_for("/add_habit Read"), env.context)

    assert env.context.user_data["pending_habit_setup"]["name"] == "Read"


async def test_explicit_none_marks_the_new_habit_as_configured(env) -> None:
    await add_habit_handler(update_for("/add_habit Rest"), env.context)

    await text_response_handler(update_for("none"), env.context)

    habit = (await env.habits.find_active_by_user(env.user.id))[0]
    assert habit.verification_policy is VerificationPolicy.NONE
    assert env.context.user_data["configured_none_habit_ids"] == [habit.id]


async def test_add_habit_treats_the_complete_tail_as_the_name(env) -> None:
    await add_habit_handler(update_for("/add_habit Learning Python --verify quiz"), env.context)

    assert env.context.user_data["pending_habit_setup"]["name"] == "Learning Python --verify quiz"
    assert env.recommender.names == ["Learning Python --verify quiz"]


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


async def test_pending_setup_has_text_priority_over_active_checkin(env) -> None:
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
    assert "Choose: quiz, photo, text, or none." in reply.message.reply_text.await_args.args[0]
