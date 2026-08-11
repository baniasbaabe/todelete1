from dataclasses import dataclass


@dataclass(frozen=True)
class ProofResult:
    verified: bool
    confidence: float
    reasoning: str
