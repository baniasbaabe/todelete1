from enum import StrEnum


class ProofType(StrEnum):
    """The kind of evidence a completion was actually recorded with."""

    NONE = "none"
    TEXT = "text"
    PHOTO = "photo"
    QUIZ = "quiz"


class VerificationPolicy(StrEnum):
    """The kind of evidence a habit demands before it counts as done.

    Deliberately a separate enum from ProofType despite the identical members:
    one describes a habit's rule, the other describes a past completion. They
    are related by ``required_proof_type`` rather than by being interchangeable,
    so a future policy with no matching proof type stays expressible.
    """

    NONE = "none"
    TEXT = "text"
    PHOTO = "photo"
    QUIZ = "quiz"

    def required_proof_type(self) -> ProofType:
        """The proof type a completion under this policy is recorded as."""
        return ProofType(self.value)
