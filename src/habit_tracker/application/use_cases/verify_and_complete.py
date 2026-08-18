from __future__ import annotations

from dataclasses import dataclass

from habit_tracker.application.ports.ai_services import ProofVerifier
from habit_tracker.application.ports.repositories import CompletionRepository
from habit_tracker.domain.entities.completion import Completion
from habit_tracker.domain.entities.habit import Habit
from habit_tracker.domain.exceptions import HabitNotFoundError, InvalidProofTypeError
from habit_tracker.domain.value_objects.proof_result import ProofResult
from habit_tracker.domain.value_objects.streak import Streak
from habit_tracker.domain.value_objects.verification_policy import ProofType, VerificationPolicy


@dataclass(frozen=True)
class VerifyAndCompleteResult:
    completion: Completion | None
    proof_result: ProofResult | None
    streak: Streak | None

    @property
    def verified(self) -> bool:
        if self.proof_result is None:
            return self.completion is not None
        return self.proof_result.verified


class VerifyAndComplete:
    def __init__(
        self,
        completion_repo: CompletionRepository,
        proof_verifier: ProofVerifier,
    ) -> None:
        self._completion_repo = completion_repo
        self._proof_verifier = proof_verifier

    async def execute(
        self,
        habit: Habit,
        proof_text: str | None = None,
        image_bytes: bytes | None = None,
        quiz_question: str | None = None,
    ) -> VerifyAndCompleteResult:
        if habit.id is None:
            raise HabitNotFoundError("Cannot record a completion against an unsaved habit")

        policy = habit.verification_policy
        if policy == VerificationPolicy.NONE:
            return await self._complete(habit, ProofType.NONE, None)

        result = await self._verify(habit, policy, proof_text, image_bytes, quiz_question)
        if not result.verified:
            return VerifyAndCompleteResult(completion=None, proof_result=result, streak=None)

        return await self._complete(habit, policy.required_proof_type(), result)

    async def _verify(
        self,
        habit: Habit,
        policy: VerificationPolicy,
        proof_text: str | None,
        image_bytes: bytes | None,
        quiz_question: str | None = None,
    ) -> ProofResult:
        """Run the check the policy calls for, rejecting proof of the wrong shape."""
        if policy == VerificationPolicy.TEXT:
            if not proof_text:
                raise InvalidProofTypeError("Text proof required for this habit")
            return await self._proof_verifier.verify_text(habit, proof_text)

        if policy == VerificationPolicy.PHOTO:
            if not image_bytes:
                raise InvalidProofTypeError("Photo proof required for this habit")
            return await self._proof_verifier.verify_image(habit, image_bytes)

        if policy == VerificationPolicy.QUIZ:
            if not proof_text or not quiz_question:
                raise InvalidProofTypeError("Quiz answer and question required for this habit")
            return await self._proof_verifier.evaluate_quiz_answer(habit, quiz_question, proof_text)

        raise InvalidProofTypeError(f"Unknown policy: {policy}")

    async def _complete(
        self,
        habit: Habit,
        proof_type: ProofType,
        result: ProofResult | None,
    ) -> VerifyAndCompleteResult:
        """Record the completion and recompute the streak it belongs to."""
        assert habit.id is not None, "habit must be persisted before completion"
        completion = Completion.create(
            habit.id,
            proof_type,
            verified=True,
            verification_notes=result.reasoning if result else None,
        )
        saved = await self._completion_repo.save(completion)
        dates = await self._completion_repo.get_completion_dates(habit.id)
        return VerifyAndCompleteResult(
            completion=saved,
            proof_result=result,
            streak=Streak.from_dates(dates, habit.frequency),
        )
