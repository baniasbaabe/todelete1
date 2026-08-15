import pytest

from habit_tracker.domain.value_objects import HabitName, VerificationPolicy
from habit_tracker.presentation.handlers.verification_setup import (
    CONFIGURED_NONE_KEY,
    PENDING_HABIT_KEY,
    PendingHabitSetup,
    clear_pending_setup,
    format_setup_prompt,
    is_none_configured,
    is_setup_cancel,
    load_pending_setup,
    mark_none_configured,
    parse_setup_choice,
    save_pending_setup,
)


def test_pending_setup_round_trips_as_plain_data() -> None:
    user_data: dict = {}
    setup = PendingHabitSetup(HabitName("Gym"), VerificationPolicy.PHOTO)

    save_pending_setup(user_data, setup)

    assert user_data[PENDING_HABIT_KEY] == {"name": "Gym", "recommendation": "photo"}
    assert load_pending_setup(user_data) == setup


def test_corrupt_pending_setup_is_removed() -> None:
    user_data: dict = {PENDING_HABIT_KEY: {"name": "", "recommendation": "not-a-policy"}}

    assert load_pending_setup(user_data) is None
    assert PENDING_HABIT_KEY not in user_data


def test_pending_setup_can_be_cleared() -> None:
    user_data: dict = {PENDING_HABIT_KEY: {"name": "Gym", "recommendation": "photo"}}

    clear_pending_setup(user_data)

    assert PENDING_HABIT_KEY not in user_data


def test_yes_is_not_a_setup_choice() -> None:
    assert parse_setup_choice(" YES ") is None


@pytest.mark.parametrize("choice", ["photo", "QUIZ", " Text ", "none"])
def test_explicit_choice_selects_exact_policy(choice: str) -> None:
    assert parse_setup_choice(choice).value == choice.strip().lower()


def test_cancel_is_distinct_from_invalid_input() -> None:
    assert is_setup_cancel(" Cancel ")
    assert not is_setup_cancel("maybe")
    assert parse_setup_choice("cancel") is None
    assert parse_setup_choice("maybe") is None


def test_confirmed_none_is_keyed_by_habit_id() -> None:
    user_data: dict = {}

    mark_none_configured(user_data, 42)

    assert is_none_configured(user_data, 42)
    assert not is_none_configured(user_data, 43)
    assert user_data[CONFIGURED_NONE_KEY] == [42]


def test_configured_none_ids_are_json_safe_integers() -> None:
    user_data: dict = {CONFIGURED_NONE_KEY: ["42", 7.0, 8.5, True, None]}

    mark_none_configured(user_data, 9)

    assert user_data[CONFIGURED_NONE_KEY] == [9]


def test_boolean_habit_id_is_rejected() -> None:
    user_data: dict = {}

    with pytest.raises(TypeError, match="habit_id must be an integer"):
        mark_none_configured(user_data, True)

    assert CONFIGURED_NONE_KEY not in user_data


def test_format_setup_prompt_uses_required_copy() -> None:
    assert format_setup_prompt(HabitName("Gym"), VerificationPolicy.PHOTO) == (
        "For \"Gym\", I recommend photo verification.\nChoose: quiz, photo, text, or none.\nReply 'cancel' to stop."
    )
