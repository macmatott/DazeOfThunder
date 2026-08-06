import pytest

from app.services.constructor_draft import (
    auto_pick_constructor_name,
    auto_pick_teammate,
    compute_naming_status,
    compute_pairing_status,
    validate_captain_order,
    validate_constructor_choice,
)

CAPTAIN_ORDER = ["A", "B", "C", "D", "E"]


def _pairs(n):
    return [{}] * n


def test_first_captain_in_order_is_on_the_clock():
    status = compute_pairing_status(CAPTAIN_ORDER, _pairs(0))
    assert status == {
        "is_complete": False,
        "on_the_clock_participant_id": "A",
        "pairs_formed": 0,
        "next_pick_number": 1,
    }


def test_next_captain_is_on_the_clock_after_a_pick():
    status = compute_pairing_status(CAPTAIN_ORDER, _pairs(2))
    assert status["on_the_clock_participant_id"] == "C"
    assert status["pairs_formed"] == 2
    assert status["next_pick_number"] == 3


def test_pairing_completes_once_every_captain_has_picked():
    status = compute_pairing_status(CAPTAIN_ORDER, _pairs(5))
    assert status["is_complete"] is True
    assert status["on_the_clock_participant_id"] is None


def test_empty_captain_order_is_immediately_complete():
    status = compute_pairing_status([], _pairs(0))
    assert status["is_complete"] is True


def test_validate_captain_order_accepts_half_of_active_roster():
    validate_captain_order(["A", "B"], {"A", "B", "C", "D"})  # no exception


def test_validate_captain_order_rejects_duplicates():
    with pytest.raises(ValueError):
        validate_captain_order(["A", "A"], {"A", "B", "C", "D"})


def test_validate_captain_order_rejects_non_active_participant():
    with pytest.raises(ValueError):
        validate_captain_order(["A", "Z"], {"A", "B", "C", "D"})


def test_validate_captain_order_rejects_wrong_captain_count():
    with pytest.raises(ValueError):
        validate_captain_order(["A"], {"A", "B", "C", "D"})


def test_validate_captain_order_rejects_empty():
    with pytest.raises(ValueError):
        validate_captain_order([], {"A", "B"})


def test_auto_pick_teammate_is_alphabetically_first_other_candidate():
    available = [
        {"id": "3", "display_name": "Zed"},
        {"id": "1", "display_name": "Alice"},
        {"id": "2", "display_name": "Bob"},
    ]
    assert auto_pick_teammate(available, on_the_clock_participant_id="9") == "1"


def test_auto_pick_teammate_never_picks_the_on_the_clock_person_themselves():
    available = [
        {"id": "1", "display_name": "Alice"},
        {"id": "2", "display_name": "Bob"},
    ]
    assert auto_pick_teammate(available, on_the_clock_participant_id="1") == "2"


def test_first_unnamed_constructor_in_descending_order_is_on_the_clock():
    rows = [
        {"id": "c5", "pick_number": 5, "name": "Ferrari"},
        {"id": "c4", "pick_number": 4, "name": None},
        {"id": "c3", "pick_number": 3, "name": None},
    ]
    status = compute_naming_status(rows)
    assert status == {
        "is_complete": False,
        "on_the_clock_constructor_id": "c4",
        "current_naming_pick_number": 2,
    }


def test_naming_completes_once_every_constructor_has_a_name():
    rows = [{"id": "c1", "pick_number": 1, "name": "Williams"}]
    status = compute_naming_status(rows)
    assert status["is_complete"] is True
    assert status["on_the_clock_constructor_id"] is None


def test_naming_with_no_constructors_is_not_complete():
    # Distinct from the driver draft's empty-order case: an empty list
    # here means naming hasn't started yet (pairing isn't done), not that
    # it's finished — there's nothing to be "complete" about yet.
    status = compute_naming_status([])
    assert status["is_complete"] is False


def test_validate_constructor_choice_rejects_unknown_team():
    with pytest.raises(ValueError):
        validate_constructor_choice("Some New Team", taken_names=set())


def test_validate_constructor_choice_rejects_already_taken():
    with pytest.raises(ValueError):
        validate_constructor_choice("Ferrari", taken_names={"Ferrari"})


def test_validate_constructor_choice_accepts_available_real_team():
    validate_constructor_choice("Ferrari", taken_names={"Williams"})  # no exception


def test_auto_pick_constructor_name_is_alphabetically_first_available():
    assert auto_pick_constructor_name(["Williams", "Ferrari", "McLaren"]) == "Ferrari"
