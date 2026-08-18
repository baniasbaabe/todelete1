from __future__ import annotations

import pytest

from habit_tracker.application.checkin_session import CheckinSession, SessionState
from habit_tracker.application.use_cases.verify_and_complete import VerifyAndComplete
from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.exceptions import InvalidProofTypeError
from habit_tracker.domain.value_objects import HabitName
from habit_tracker.domain.value_objects.verification_policy import ProofType, VerificationPolicy
from tests.unit.conftest import FakeProofVerifier, InMemoryCompletionRepository


def _quiz_habit(habit_id: int = 1) -> Habit:
    h = Habit.create(user_id=1, name=HabitName("learn ML"), verification_policy=VerificationPolicy.QUIZ)
    h.id = habit_id
    return h


class TestQuizVerification:
    async def test_quiz_verified(self):
        repo = InMemoryCompletionRepository()
        uc = VerifyAndComplete(repo, FakeProofVerifier(result_verified=True))
        result = await uc.execute(_quiz_habit(), proof_text="4", quiz_question="What is 2+2?")
        assert result.verified is True
        assert result.completion is not None

    async def test_quiz_rejected(self):
        repo = InMemoryCompletionRepository()
        uc = VerifyAndComplete(repo, FakeProofVerifier(result_verified=False))
        result = await uc.execute(_quiz_habit(), proof_text="wrong", quiz_question="What is 2+2?")
        assert result.verified is False
        assert result.completion is None

    async def test_quiz_requires_both_answer_and_question(self):
        repo = InMemoryCompletionRepository()
        uc = VerifyAndComplete(repo, FakeProofVerifier())
        with pytest.raises(InvalidProofTypeError):
            await uc.execute(_quiz_habit(), proof_text="answer")

    async def test_quiz_requires_answer(self):
        repo = InMemoryCompletionRepository()
        uc = VerifyAndComplete(repo, FakeProofVerifier())
        with pytest.raises(InvalidProofTypeError):
            await uc.execute(_quiz_habit(), quiz_question="What is 2+2?")

    async def test_quiz_habit_requires_proof(self):
        assert _quiz_habit().requires_proof() is True

    async def test_quiz_policy_maps_to_quiz_proof_type(self):
        assert VerificationPolicy.QUIZ.required_proof_type() is ProofType.QUIZ


class TestQuizSessionStateMachine:
    """The quiz flow has three states: topic → question → answer."""

    def test_initial_state_is_awaiting_response(self):
        session = CheckinSession.start(user_id=1, habits=[_quiz_habit()])
        assert session.state == SessionState.AWAITING_RESPONSE
        assert session.quiz_question is None

    def test_yes_transitions_to_awaiting_topic(self):
        session = CheckinSession.start(user_id=1, habits=[_quiz_habit()])
        session.state = SessionState.AWAITING_QUIZ_TOPIC
        assert session.state == SessionState.AWAITING_QUIZ_TOPIC

    def test_topic_transitions_to_awaiting_answer(self):
        session = CheckinSession.start(user_id=1, habits=[_quiz_habit()])
        session.state = SessionState.AWAITING_QUIZ_ANSWER
        session.quiz_question = "What does gradient descent minimize?"
        assert session.quiz_question == "What does gradient descent minimize?"

    def test_advance_resets_to_awaiting_response(self):
        session = CheckinSession.start(user_id=1, habits=[_quiz_habit(), _quiz_habit(2)])
        session.state = SessionState.AWAITING_QUIZ_ANSWER
        session.quiz_question = "What is ML?"
        session.record_completion()
        session.advance()
        assert session.state == SessionState.AWAITING_RESPONSE

    def test_full_state_machine_flow(self):
        """yes → topic → question → answer → advance."""
        session = CheckinSession.start(user_id=1, habits=[_quiz_habit(), _quiz_habit(2)])

        # Step 1: user says "yes" → handler sets AWAITING_QUIZ_TOPIC
        session.state = SessionState.AWAITING_QUIZ_TOPIC

        # Step 2: user provides topic → handler generates question, sets AWAITING_QUIZ_ANSWER
        session.state = SessionState.AWAITING_QUIZ_ANSWER
        session.quiz_question = "Explain overfitting in one sentence."

        # Step 3: user answers → handler evaluates, records result, advances
        session.record_completion()
        session.quiz_question = None
        next_habit = session.advance()

        assert next_habit is not None
        assert session.state == SessionState.AWAITING_RESPONSE
        assert session.quiz_question is None


class TestQuizSerialization:
    def test_roundtrip_with_quiz_topic_state(self):
        session = CheckinSession.start(user_id=1, habits=[_quiz_habit()])
        session.state = SessionState.AWAITING_QUIZ_TOPIC

        restored = CheckinSession.from_dict(session.to_dict())
        assert restored.state == SessionState.AWAITING_QUIZ_TOPIC
        assert restored.quiz_question is None

    def test_roundtrip_with_quiz_answer_state(self):
        session = CheckinSession.start(user_id=1, habits=[_quiz_habit()])
        session.state = SessionState.AWAITING_QUIZ_ANSWER
        session.quiz_question = "Explain overfitting."

        restored = CheckinSession.from_dict(session.to_dict())
        assert restored.state == SessionState.AWAITING_QUIZ_ANSWER
        assert restored.quiz_question == "Explain overfitting."

    def test_backward_compatible_without_quiz_question_key(self):
        """Sessions serialized before quiz support lack the quiz_question key."""
        data = {
            "user_id": 1,
            "current_index": 0,
            "state": "awaiting_response",
            "created_at": "2026-01-01T00:00:00+00:00",
            "habits": [
                {
                    "id": 1,
                    "user_id": 1,
                    "name": "gym",
                    "description": None,
                    "frequency": "daily",
                    "verification_policy": "none",
                    "is_active": True,
                    "created_at": "2026-01-01T00:00:00+00:00",
                }
            ],
            "results": [],
        }
        restored = CheckinSession.from_dict(data)
        assert restored.quiz_question is None
