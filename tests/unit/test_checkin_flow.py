"""End-to-end check-in flow through the real handlers.

The presentation layer previously had no tests at all, which is why a total
outage (dependencies wiped at startup) and an inert memory feature both went
unnoticed. These drive the real handler functions, substituting only the
transaction boundary and the external services.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.ext import ApplicationBuilder

from habit_tracker.application.checkin_session import TTL_HOURS, CheckinSession
from habit_tracker.application.use_cases.create_habit import CreateHabit
from habit_tracker.application.use_cases.record_checkin_insight import INSIGHT_CATEGORY
from habit_tracker.application.use_cases.register_user import RegisterUser
from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.value_objects import HabitName, TelegramId
from habit_tracker.domain.value_objects.verification_policy import VerificationPolicy
from habit_tracker.infrastructure.database.unit_of_work import UnitOfWork
from habit_tracker.infrastructure.persistence.postgres_persistence import PostgresPersistence
from habit_tracker.presentation.dependencies import Dependencies, install
from habit_tracker.presentation.handlers.checkin_handlers import checkin_handler
from habit_tracker.presentation.handlers.proof_handlers import text_response_handler
from habit_tracker.presentation.handlers.verification_setup import is_none_configured, mark_none_configured
from tests.unit.conftest import (
    FakeMemoryStore,
    FakePatternAnalyzer,
    FakeProofVerifier,
    FakeVerificationRecommender,
    InMemoryCompletionRepository,
    InMemoryHabitRepository,
    InMemoryUserRepository,
)

TELEGRAM_ID = 987654


class _InMemoryDependencies(Dependencies):
    """Dependencies whose unit of work is backed by the in-memory repositories."""

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
def env():
    users = InMemoryUserRepository()
    habits = InMemoryHabitRepository()
    completions = InMemoryCompletionRepository()
    memory = FakeMemoryStore()

    recommender = FakeVerificationRecommender(VerificationPolicy.PHOTO)
    deps = _InMemoryDependencies(
        users,
        habits,
        completions,
        proof_verifier=FakeProofVerifier(result_verified=True),
        memory_store=memory,
        pattern_analyzer=FakePatternAnalyzer(),
        verification_recommender=recommender,
    )

    app = ApplicationBuilder().token("123:ABC").build()
    install(app, deps)

    context = SimpleNamespace(application=app, user_data={}, bot=None)
    return SimpleNamespace(
        users=users,
        habits=habits,
        completions=completions,
        memory=memory,
        recommender=recommender,
        uow_session=deps.uow_session,
        app=app,
        context=context,
    )


def _update(text: str | None = None) -> SimpleNamespace:
    message = SimpleNamespace(text=text, reply_text=AsyncMock(), photo=[])
    return SimpleNamespace(message=message, effective_user=SimpleNamespace(id=TELEGRAM_ID, username="tester"))


async def _seed(env, *, policy: VerificationPolicy = VerificationPolicy.NONE, configured_none: bool = True):
    user, _ = await RegisterUser(env.users).execute(TelegramId(TELEGRAM_ID))
    habit = await CreateHabit(env.users, env.habits).execute(
        TelegramId(TELEGRAM_ID), HabitName("gym"), verification_policy=policy
    )
    if policy is VerificationPolicy.NONE and configured_none:
        assert habit.id is not None
        mark_none_configured(env.context.user_data, habit.id)
    return user


async def _drain_background_tasks(app) -> None:
    """Await the fire-and-forget insight write."""
    for _ in range(5):
        await asyncio.sleep(0)
    if app._Application__create_task_tasks:
        await asyncio.gather(*app._Application__create_task_tasks, return_exceptions=True)


class TestCheckinFlow:
    async def test_checkin_opens_a_session(self, env) -> None:
        await _seed(env)
        update = _update()

        await checkin_handler(update, env.context)

        assert "checkin_session" in env.context.user_data
        update.message.reply_text.assert_awaited_once()
        assert "gym" in update.message.reply_text.await_args.args[0]

    async def test_session_stores_persistent_user_id_not_telegram_id(self, env) -> None:
        user = await _seed(env)

        await checkin_handler(_update(), env.context)

        assert env.context.user_data["checkin_session"]["user_id"] == user.id
        assert env.context.user_data["checkin_session"]["user_id"] != TELEGRAM_ID

    async def test_completing_a_checkin_records_a_memory_insight(self, env) -> None:
        """The write half of the memory feature, exercised through the handlers."""
        user = await _seed(env)
        await checkin_handler(_update(), env.context)

        reply = _update("yes")
        await text_response_handler(reply, env.context)
        await _drain_background_tasks(env.app)

        assert len(env.memory.stored) == 1
        assert env.memory.stored[0]["user_id"] == user.id
        assert env.memory.stored[0]["category"] == INSIGHT_CATEGORY
        assert "completed gym" in env.memory.stored[0]["insight"]

    async def test_insight_is_readable_back_under_the_same_user_id(self, env) -> None:
        user = await _seed(env)
        await checkin_handler(_update(), env.context)

        await text_response_handler(_update("yes"), env.context)
        await _drain_background_tasks(env.app)

        assert len(await env.memory.get_insights(user.id)) == 1
        assert await env.memory.get_insights(TELEGRAM_ID) == []

    async def test_completing_a_checkin_clears_the_session(self, env) -> None:
        await _seed(env)
        await checkin_handler(_update(), env.context)

        await text_response_handler(_update("yes"), env.context)

        assert "checkin_session" not in env.context.user_data

    @pytest.mark.parametrize("second_reply", ["yes", "skip"])
    async def test_second_habit_finishes_after_persistence_refresh(self, env, monkeypatch, second_reply: str) -> None:
        await _seed(env)
        second = await CreateHabit(env.users, env.habits).execute(TelegramId(TELEGRAM_ID), HabitName("read"))
        assert second.id is not None
        mark_none_configured(env.context.user_data, second.id)
        await checkin_handler(_update(), env.context)
        stale_user_data = deepcopy(env.context.user_data)

        first_reply = _update("yes")
        await text_response_handler(first_reply, env.context)
        assert "read" in first_reply.message.reply_text.await_args.args[0]

        persistence = PostgresPersistence("postgresql+asyncpg://u:p@host:5432/db")

        async def load_stale_user_data(key: str) -> dict:
            return stale_user_data

        monkeypatch.setattr(persistence, "_load_one", load_stale_user_data)
        await persistence.refresh_user_data(TELEGRAM_ID, env.context.user_data)

        final_reply = _update(second_reply)
        await text_response_handler(final_reply, env.context)

        assert "checkin_session" not in env.context.user_data
        assert "check-in complete" in final_reply.message.reply_text.await_args.args[0].lower()

    async def test_skip_is_recorded_as_not_completed(self, env) -> None:
        await _seed(env)
        await checkin_handler(_update(), env.context)

        await text_response_handler(_update("skip"), env.context)
        await _drain_background_tasks(env.app)

        assert "skipped gym" in env.memory.stored[0]["insight"]

    async def test_unrecognised_input_reprompts_instead_of_going_silent(self, env) -> None:
        await _seed(env)
        await checkin_handler(_update(), env.context)

        reply = _update("maybe later")
        await text_response_handler(reply, env.context)

        reply.message.reply_text.assert_awaited_once()
        assert "didn't catch that" in reply.message.reply_text.await_args.args[0]
        assert "checkin_session" in env.context.user_data

    async def test_text_outside_a_checkin_is_ignored(self, env) -> None:
        await _seed(env)
        reply = _update("hello")

        await text_response_handler(reply, env.context)

        reply.message.reply_text.assert_not_awaited()

    async def test_corrupt_session_is_dropped_rather_than_trapping_the_user(self, env) -> None:
        """A session persisted by an older release must not wedge the check-in."""
        await _seed(env)
        env.context.user_data["checkin_session"] = {"user_id": 1}  # missing keys

        reply = _update("yes")
        await text_response_handler(reply, env.context)

        assert "checkin_session" not in env.context.user_data
        reply.message.reply_text.assert_not_awaited()

    async def test_checkin_recovers_from_a_corrupt_session(self, env) -> None:
        """/checkin decoded the stored session unguarded and raised on a bad one."""
        await _seed(env)
        env.context.user_data["checkin_session"] = {"user_id": 1}  # missing keys

        update = _update()
        await checkin_handler(update, env.context)

        assert "gym" in update.message.reply_text.await_args.args[0]
        assert env.context.user_data["checkin_session"]["habits"]

    async def test_expired_session_is_replaced_by_a_fresh_one(self, env) -> None:
        await _seed(env)
        await checkin_handler(_update(), env.context)
        stale = env.context.user_data["checkin_session"]
        stale["created_at"] = (datetime.now(UTC) - timedelta(hours=TTL_HOURS + 1)).isoformat()

        update = _update()
        await checkin_handler(update, env.context)

        assert "gym" in update.message.reply_text.await_args.args[0]
        assert env.context.user_data["checkin_session"]["created_at"] != stale["created_at"]

    async def test_legacy_none_habit_starts_with_setup_prompt(self, env) -> None:
        await _seed(env, policy=VerificationPolicy.NONE, configured_none=False)
        update = _update()

        await checkin_handler(update, env.context)

        session = env.context.user_data["checkin_session"]
        assert session["state"] == "awaiting_verification_setup"
        assert session["verification_recommendation"] == "photo"
        prompt = update.message.reply_text.await_args.args[0].lower()
        assert "recommend photo" in prompt
        assert "'skip'" in prompt
        assert "'cancel'" not in prompt

    async def test_selecting_recommended_photo_updates_without_advancing(self, env) -> None:
        await _seed(env, policy=VerificationPolicy.NONE, configured_none=False)
        await checkin_handler(_update(), env.context)
        reply = _update("yes")

        await text_response_handler(reply, env.context)

        session = env.context.user_data["checkin_session"]
        assert session["current_index"] == 0
        assert session["state"] == "awaiting_response"
        assert session["habits"][0]["verification_policy"] == "photo"
        assert session["results"] == []
        assert await env.completions.find_today_by_habits([session["habits"][0]["id"]]) == []
        assert (await env.habits.find_by_id(session["habits"][0]["id"])).verification_policy is VerificationPolicy.PHOTO
        env.uow_session.commit.assert_awaited_once()
        assert "verification set to photo" in reply.message.reply_text.await_args.args[0].lower()
        assert "submit photo proof" in reply.message.reply_text.await_args.args[0].lower()

    @pytest.mark.parametrize("choice", ["photo", "quiz", "text", "none"])
    async def test_explicit_setup_choice_is_persisted(self, env, choice: str) -> None:
        await _seed(env, policy=VerificationPolicy.NONE, configured_none=False)
        await checkin_handler(_update(), env.context)

        await text_response_handler(_update(choice), env.context)

        session = env.context.user_data["checkin_session"]
        habit_id = session["habits"][0]["id"]
        stored = await env.habits.find_by_id(habit_id)
        assert stored is not None
        assert stored.verification_policy is VerificationPolicy(choice)
        assert session["habits"][0]["verification_policy"] == choice
        assert session["state"] == "awaiting_response"
        assert session["current_index"] == 0
        assert is_none_configured(env.context.user_data, habit_id) is (choice == "none")

    async def test_invalid_setup_choice_keeps_setup_active(self, env) -> None:
        await _seed(env, policy=VerificationPolicy.NONE, configured_none=False)
        await checkin_handler(_update(), env.context)
        reply = _update("maybe")

        await text_response_handler(reply, env.context)

        session = env.context.user_data["checkin_session"]
        assert session["state"] == "awaiting_verification_setup"
        assert session["current_index"] == 0
        assert session["verification_recommendation"] == "photo"
        prompt = reply.message.reply_text.await_args.args[0].lower()
        assert "recommend photo" in prompt
        assert "'skip'" in prompt
        assert "'cancel'" not in prompt
        env.uow_session.commit.assert_not_awaited()

    async def test_skip_during_setup_advances_without_configuring_habit(self, env) -> None:
        await _seed(env, policy=VerificationPolicy.NONE, configured_none=False)
        await checkin_handler(_update(), env.context)
        habit_id = env.context.user_data["checkin_session"]["habits"][0]["id"]

        await text_response_handler(_update("skip"), env.context)
        await _drain_background_tasks(env.app)

        assert "checkin_session" not in env.context.user_data
        assert not is_none_configured(env.context.user_data, habit_id)
        assert (await env.habits.find_by_id(habit_id)).verification_policy is VerificationPolicy.NONE
        assert await env.completions.find_today_by_habits([habit_id]) == []
        assert "skipped gym" in env.memory.stored[0]["insight"]

        retry = _update()
        await checkin_handler(retry, env.context)
        assert env.context.user_data["checkin_session"]["state"] == "awaiting_verification_setup"
        assert "recommend photo" in retry.message.reply_text.await_args.args[0].lower()

    async def test_resumed_legacy_setup_reuses_recommendation(self, env) -> None:
        await _seed(env, policy=VerificationPolicy.NONE, configured_none=False)
        await checkin_handler(_update(), env.context)
        resumed = _update()

        await checkin_handler(resumed, env.context)

        session = env.context.user_data["checkin_session"]
        assert session["state"] == "awaiting_verification_setup"
        assert session["verification_recommendation"] == "photo"
        assert env.recommender.names == ["gym"]
        assert "active check-in" in resumed.message.reply_text.await_args.args[0].lower()
        prompt = resumed.message.reply_text.await_args.args[0].lower()
        assert "recommend photo" in prompt
        assert "'skip'" in prompt
        assert "'cancel'" not in prompt

    async def test_reissuing_checkin_preserves_awaiting_photo_proof(self, env) -> None:
        await _seed(env, policy=VerificationPolicy.PHOTO)
        await checkin_handler(_update(), env.context)
        await text_response_handler(_update("yes"), env.context)
        resumed = _update()

        await checkin_handler(resumed, env.context)

        assert env.context.user_data["checkin_session"]["state"] == "awaiting_proof"
        prompt = resumed.message.reply_text.await_args.args[0].lower()
        assert "active check-in" in prompt
        assert "send your photo proof" in prompt

    async def test_reissuing_checkin_preserves_awaiting_quiz_topic(self, env) -> None:
        await _seed(env, policy=VerificationPolicy.QUIZ)
        await checkin_handler(_update(), env.context)
        await text_response_handler(_update("yes"), env.context)
        resumed = _update()

        await checkin_handler(resumed, env.context)

        assert env.context.user_data["checkin_session"]["state"] == "awaiting_quiz_topic"
        prompt = resumed.message.reply_text.await_args.args[0].lower()
        assert "active check-in" in prompt
        assert "what did you learn about today" in prompt

    async def test_reissuing_checkin_preserves_awaiting_quiz_answer(self, env) -> None:
        await _seed(env, policy=VerificationPolicy.QUIZ)
        await checkin_handler(_update(), env.context)
        await text_response_handler(_update("yes"), env.context)
        await text_response_handler(_update("overfitting"), env.context)
        resumed = _update()

        await checkin_handler(resumed, env.context)

        session = env.context.user_data["checkin_session"]
        assert session["state"] == "awaiting_quiz_answer"
        assert session["quiz_question"] == "What is 2+2?"
        prompt = resumed.message.reply_text.await_args.args[0].lower()
        assert "active check-in" in prompt
        assert "what is 2+2?" in prompt

    async def test_old_awaiting_response_none_session_is_migrated_before_yes(self, env) -> None:
        user = await _seed(env, policy=VerificationPolicy.NONE, configured_none=False)
        habits = await env.habits.find_active_by_user(user.id)
        old_session = CheckinSession.start(user.id, habits).to_dict()
        old_session.pop("verification_recommendation")
        env.context.user_data["checkin_session"] = old_session
        reply = _update("yes")

        await text_response_handler(reply, env.context)

        session = env.context.user_data["checkin_session"]
        habit_id = session["habits"][0]["id"]
        assert session["state"] == "awaiting_verification_setup"
        assert session["verification_recommendation"] == "photo"
        assert session["results"] == []
        assert await env.completions.find_today_by_habits([habit_id]) == []
        assert "recommend photo" in reply.message.reply_text.await_args.args[0].lower()

    async def test_setup_update_failure_leaves_current_habit_pending(self, env, monkeypatch) -> None:
        await _seed(env, policy=VerificationPolicy.NONE, configured_none=False)
        await checkin_handler(_update(), env.context)
        habit_id = env.context.user_data["checkin_session"]["habits"][0]["id"]
        find_stored = env.habits.find_by_id

        async def find_copy(candidate_id: int) -> Habit | None:
            habit = await find_stored(candidate_id)
            return deepcopy(habit)

        monkeypatch.setattr(env.habits, "find_by_id", find_copy)
        monkeypatch.setattr(env.habits, "save", AsyncMock(side_effect=ValueError("write failed")))
        reply = _update("photo")

        await text_response_handler(reply, env.context)

        session = env.context.user_data["checkin_session"]
        assert session["state"] == "awaiting_verification_setup"
        assert session["current_index"] == 0
        assert session["habits"][0]["verification_policy"] == "none"
        assert session["results"] == []
        stored = await find_stored(habit_id)
        assert stored is not None
        assert stored.verification_policy is VerificationPolicy.NONE
        env.uow_session.commit.assert_not_awaited()
        assert "could not update verification" in reply.message.reply_text.await_args.args[0].lower()

    async def test_advancing_prepares_a_second_legacy_habit(self, env) -> None:
        await _seed(env, policy=VerificationPolicy.NONE, configured_none=False)
        second = await CreateHabit(env.users, env.habits).execute(TelegramId(TELEGRAM_ID), HabitName("read"))
        await checkin_handler(_update(), env.context)
        await text_response_handler(_update("none"), env.context)
        advance = _update("yes")

        await text_response_handler(advance, env.context)

        session = env.context.user_data["checkin_session"]
        assert session["current_index"] == 1
        assert session["state"] == "awaiting_verification_setup"
        assert session["verification_recommendation"] == "photo"
        assert len(session["results"]) == 1
        assert second.id is not None
        assert not is_none_configured(env.context.user_data, second.id)
        prompt = advance.message.reply_text.await_args.args[0].lower()
        assert "recommend photo" in prompt
        assert "'skip'" in prompt
        assert "'cancel'" not in prompt

    async def test_legacy_photo_setup_continues_to_proof_without_completion(self, env) -> None:
        await _seed(env, policy=VerificationPolicy.NONE, configured_none=False)
        await checkin_handler(_update(), env.context)
        await text_response_handler(_update("photo"), env.context)
        reply = _update("yes")

        await text_response_handler(reply, env.context)

        session = env.context.user_data["checkin_session"]
        habit_id = session["habits"][0]["id"]
        assert session["state"] == "awaiting_proof"
        assert session["current_index"] == 0
        assert session["results"] == []
        assert await env.completions.find_today_by_habits([habit_id]) == []
        assert "send your photo proof" in reply.message.reply_text.await_args.args[0].lower()

    async def test_legacy_quiz_setup_completes_exactly_once(self, env) -> None:
        await _seed(env, policy=VerificationPolicy.NONE, configured_none=False)
        await checkin_handler(_update(), env.context)
        await text_response_handler(_update("quiz"), env.context)

        topic_prompt = _update("yes")
        await text_response_handler(topic_prompt, env.context)
        assert env.context.user_data["checkin_session"]["state"] == "awaiting_quiz_topic"
        assert "what did you learn" in topic_prompt.message.reply_text.await_args.args[0].lower()

        question = _update("overfitting")
        await text_response_handler(question, env.context)
        session = env.context.user_data["checkin_session"]
        assert session["state"] == "awaiting_quiz_answer"
        assert session["quiz_question"] == "What is 2+2?"
        assert "what is 2+2?" in question.message.reply_text.await_args.args[0].lower()

        answer = _update("four")
        habit_id = session["habits"][0]["id"]
        await text_response_handler(answer, env.context)
        await _drain_background_tasks(env.app)

        completions = await env.completions.find_today_by_habits([habit_id])
        assert len(completions) == 1
        assert completions[0].proof_type.value == "quiz"
        assert (await env.habits.find_by_id(habit_id)).verification_policy is VerificationPolicy.QUIZ
        assert "checkin_session" not in env.context.user_data
        assert "check-in complete" in answer.message.reply_text.await_args.args[0].lower()
        assert "completed gym" in env.memory.stored[0]["insight"]
        assert env.uow_session.commit.await_count == 2

    async def test_proof_habit_asks_for_proof_before_completing(self, env) -> None:
        await _seed(env, policy=VerificationPolicy.TEXT)
        await checkin_handler(_update(), env.context)

        reply = _update("yes")
        await text_response_handler(reply, env.context)

        assert "proof" in reply.message.reply_text.await_args.args[0].lower()
        assert env.context.user_data["checkin_session"]["state"] == "awaiting_proof"
        assert env.memory.stored == []

    async def test_proof_habit_completes_after_proof_is_verified(self, env) -> None:
        await _seed(env, policy=VerificationPolicy.TEXT)
        await checkin_handler(_update(), env.context)
        await text_response_handler(_update("yes"), env.context)

        await text_response_handler(_update("I ran 5km this morning"), env.context)
        await _drain_background_tasks(env.app)

        assert "checkin_session" not in env.context.user_data
        assert "completed gym" in env.memory.stored[0]["insight"]
