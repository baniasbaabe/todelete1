from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.value_objects import (
    Frequency,
    HabitName,
    ProofType,
    VerificationPolicy,
)


class TestHabitCreate:
    def test_creates_with_defaults(self):
        habit = Habit.create(user_id=1, name=HabitName("gym"))
        assert habit.id is None
        assert habit.user_id == 1
        assert habit.name == HabitName("gym")
        assert habit.frequency == Frequency.DAILY
        assert habit.verification_policy == VerificationPolicy.NONE
        assert habit.is_active is True

    def test_creates_with_photo_policy(self):
        habit = Habit.create(
            user_id=1,
            name=HabitName("gym"),
            verification_policy=VerificationPolicy.PHOTO,
        )
        assert habit.verification_policy == VerificationPolicy.PHOTO


class TestHabitBehavior:
    def test_deactivate(self):
        habit = Habit.create(user_id=1, name=HabitName("gym"))
        habit.deactivate()
        assert habit.is_active is False

    def test_requires_proof_none(self):
        habit = Habit.create(user_id=1, name=HabitName("gym"))
        assert habit.requires_proof() is False

    def test_requires_proof_text(self):
        habit = Habit.create(
            user_id=1,
            name=HabitName("read"),
            verification_policy=VerificationPolicy.TEXT,
        )
        assert habit.requires_proof() is True

    def test_requires_proof_photo(self):
        habit = Habit.create(
            user_id=1,
            name=HabitName("gym"),
            verification_policy=VerificationPolicy.PHOTO,
        )
        assert habit.requires_proof() is True

    def test_policy_maps_to_the_proof_type_completions_are_recorded_as(self):
        assert VerificationPolicy.PHOTO.required_proof_type() is ProofType.PHOTO
        assert VerificationPolicy.TEXT.required_proof_type() is ProofType.TEXT
        assert VerificationPolicy.NONE.required_proof_type() is ProofType.NONE

    def test_every_policy_has_a_proof_type(self):
        """The two enums are separate; this is the bridge that keeps them in step."""
        for policy in VerificationPolicy:
            assert policy.required_proof_type() in ProofType
