from __future__ import annotations

import pytest

from habit_tracker.domain.value_objects.verification_policy import VerificationPolicy
from habit_tracker.presentation.handlers.command_handlers import _parse_add_habit_args


def test_add_habit_parser_accepts_a_valid_verification_policy() -> None:
    name, policy = _parse_add_habit_args("Morning run --verify photo")

    assert name.value == "Morning run"
    assert policy is VerificationPolicy.PHOTO


def test_add_habit_parser_defaults_to_no_verification() -> None:
    name, policy = _parse_add_habit_args("Morning run")

    assert name.value == "Morning run"
    assert policy is VerificationPolicy.NONE


@pytest.mark.parametrize(
    "raw",
    [
        "Morning run --verify phohto",
        "Morning run --verify",
        "Morning run --verify photo extra",
        "Morning run --verify photo --verify text",
        "Morning run --verify=photo",
        "Morning run --verify-photo",
        "Morning run --Verify photo",
        "Morning run --verif photo",
    ],
)
def test_add_habit_parser_rejects_malformed_verification_policy(raw: str) -> None:
    with pytest.raises(ValueError, match="text, photo, or quiz"):
        _parse_add_habit_args(raw)
