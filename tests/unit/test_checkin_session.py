from datetime import UTC, datetime, timedelta

from habit_tracker.application.checkin_session import (
    CheckinSession,
    SessionState,
)
from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.value_objects import HabitName, VerificationPolicy


def _make_habit(name: str, habit_id: int = 1) -> Habit:
    habit = Habit.create(user_id=1, name=HabitName(name))
    habit.id = habit_id
    return habit


class TestCheckinSession:
    def test_initial_state(self):
        habits = [_make_habit("gym", 1), _make_habit("read", 2)]
        session = CheckinSession.start(user_id=1, habits=habits)
        assert session.state == SessionState.AWAITING_RESPONSE
        assert session.current_habit() == habits[0]
        assert session.is_complete() is False

    def test_advance_to_next_habit(self):
        habits = [_make_habit("gym", 1), _make_habit("read", 2)]
        session = CheckinSession.start(user_id=1, habits=habits)
        session.record_skip()
        next_habit = session.advance()
        assert next_habit == habits[1]
        assert session.state == SessionState.AWAITING_RESPONSE

    def test_advance_past_last_habit(self):
        session = CheckinSession.start(user_id=1, habits=[_make_habit("gym", 1)])
        session.record_skip()
        next_habit = session.advance()
        assert next_habit is None
        assert session.is_complete() is True
        assert session.state == SessionState.DONE

    def test_record_completion(self):
        session = CheckinSession.start(user_id=1, habits=[_make_habit("gym", 1)])
        session.record_completion()
        summary = session.get_summary()
        assert summary.total == 1
        assert summary.completed == 1

    def test_set_awaiting_proof(self):
        session = CheckinSession.start(user_id=1, habits=[_make_habit("gym", 1)])
        session.state = SessionState.AWAITING_PROOF
        assert session.state == SessionState.AWAITING_PROOF

    def test_expired_after_24h(self):
        session = CheckinSession.start(user_id=1, habits=[_make_habit("gym", 1)])
        session.created_at = datetime.now(UTC) - timedelta(hours=25)
        assert session.is_expired() is True

    def test_not_expired_within_24h(self):
        session = CheckinSession.start(user_id=1, habits=[_make_habit("gym", 1)])
        assert session.is_expired() is False

    def test_serialization_roundtrip(self):
        habits = [_make_habit("gym", 1), _make_habit("read", 2)]
        session = CheckinSession.start(user_id=1, habits=habits)
        session.record_skip()
        session.advance()

        data = session.to_dict()
        restored = CheckinSession.from_dict(data)

        assert restored.user_id == session.user_id
        assert restored.current_index == session.current_index
        assert restored.state == session.state
        assert len(restored.habits) == len(session.habits)

    def test_verification_setup_state_round_trips(self):
        session = CheckinSession.start(user_id=1, habits=[_make_habit("gym", 1)])
        session.state = SessionState.AWAITING_VERIFICATION_SETUP
        session.verification_recommendation = VerificationPolicy.PHOTO

        restored = CheckinSession.from_dict(session.to_dict())

        assert restored.state is SessionState.AWAITING_VERIFICATION_SETUP
        assert restored.verification_recommendation is VerificationPolicy.PHOTO

    def test_old_session_without_recommendation_still_decodes(self):
        session = CheckinSession.start(user_id=1, habits=[_make_habit("gym", 1)])
        data = session.to_dict()
        data.pop("verification_recommendation")

        restored = CheckinSession.from_dict(data)

        assert restored.verification_recommendation is None

    def test_advance_clears_verification_recommendation(self):
        session = CheckinSession.start(user_id=1, habits=[_make_habit("gym", 1), _make_habit("read", 2)])
        session.verification_recommendation = VerificationPolicy.PHOTO

        session.advance()

        assert session.verification_recommendation is None
