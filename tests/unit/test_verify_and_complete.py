import pytest

from habit_tracker.application.use_cases.verify_and_complete import VerifyAndComplete
from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.exceptions import InvalidProofTypeError
from habit_tracker.domain.value_objects import HabitName, VerificationPolicy
from tests.unit.conftest import FakeProofVerifier, InMemoryCompletionRepository


def _habit(policy: VerificationPolicy, habit_id: int = 1) -> Habit:
    h = Habit.create(user_id=1, name=HabitName("test"), verification_policy=policy)
    h.id = habit_id
    return h


@pytest.fixture
def completion_repo():
    return InMemoryCompletionRepository()


class TestVerifyAndComplete:
    async def test_none_policy_auto_completes(self, completion_repo):
        uc = VerifyAndComplete(completion_repo, FakeProofVerifier())
        result = await uc.execute(_habit(VerificationPolicy.NONE))
        assert result.verified is True
        assert result.completion is not None
        assert result.proof_result is None
        assert result.streak is not None

    async def test_text_verified(self, completion_repo):
        uc = VerifyAndComplete(completion_repo, FakeProofVerifier(result_verified=True))
        result = await uc.execute(_habit(VerificationPolicy.TEXT), proof_text="I ran 5km")
        assert result.verified is True
        assert result.completion is not None

    async def test_text_rejected(self, completion_repo):
        uc = VerifyAndComplete(completion_repo, FakeProofVerifier(result_verified=False))
        result = await uc.execute(_habit(VerificationPolicy.TEXT), proof_text="maybe")
        assert result.verified is False
        assert result.completion is None
        assert result.proof_result is not None

    async def test_photo_verified(self, completion_repo):
        uc = VerifyAndComplete(completion_repo, FakeProofVerifier(result_verified=True))
        result = await uc.execute(_habit(VerificationPolicy.PHOTO), image_bytes=b"fake-image")
        assert result.verified is True

    async def test_text_required_but_missing(self, completion_repo):
        uc = VerifyAndComplete(completion_repo, FakeProofVerifier())
        with pytest.raises(InvalidProofTypeError):
            await uc.execute(_habit(VerificationPolicy.TEXT))

    async def test_photo_required_but_missing(self, completion_repo):
        uc = VerifyAndComplete(completion_repo, FakeProofVerifier())
        with pytest.raises(InvalidProofTypeError):
            await uc.execute(_habit(VerificationPolicy.PHOTO))
