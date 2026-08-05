from datetime import datetime, timedelta, timezone

import pytest

from app.services.draft import (
    PICK_TIMER_SECONDS,
    _sort_by_fantasy_points,
    compute_draft_status,
    compute_seconds_remaining,
    get_turn_started_at,
    is_pick_expired,
    logo_url_for_team,
    validate_draft_order,
)

ORDER = ["A", "B", "C"]


def _picks(n):
    """n dummy already-made picks — compute_draft_status only needs len()."""
    return [{}] * n


def test_first_pick_is_first_in_order():
    status = compute_draft_status(ORDER, total_rounds=2, picks=_picks(0))
    assert status == {
        "is_complete": False,
        "current_round": 1,
        "current_pick_number": 1,
        "on_the_clock_participant_id": "A",
    }


def test_round_one_goes_forward():
    assert compute_draft_status(ORDER, 2, _picks(1))["on_the_clock_participant_id"] == "B"
    assert compute_draft_status(ORDER, 2, _picks(2))["on_the_clock_participant_id"] == "C"


def test_round_two_snakes_backward():
    # Round 2 starts with whoever picked last in round 1 (C), not A again.
    status = compute_draft_status(ORDER, 2, _picks(3))
    assert status["current_round"] == 2
    assert status["current_pick_number"] == 4
    assert status["on_the_clock_participant_id"] == "C"

    assert compute_draft_status(ORDER, 2, _picks(4))["on_the_clock_participant_id"] == "B"
    assert compute_draft_status(ORDER, 2, _picks(5))["on_the_clock_participant_id"] == "A"


def test_draft_completes_after_n_times_total_rounds_picks():
    status = compute_draft_status(ORDER, 2, _picks(6))
    assert status == {
        "is_complete": True,
        "current_round": None,
        "current_pick_number": None,
        "on_the_clock_participant_id": None,
    }


def test_empty_draft_order_is_immediately_complete():
    status = compute_draft_status([], 2, _picks(0))
    assert status["is_complete"] is True


def test_single_participant_picks_once_per_round():
    solo = ["A"]
    assert compute_draft_status(solo, 2, _picks(0))["on_the_clock_participant_id"] == "A"
    first = compute_draft_status(solo, 2, _picks(0))
    assert first["current_round"] == 1
    second = compute_draft_status(solo, 2, _picks(1))
    assert second["current_round"] == 2
    assert second["on_the_clock_participant_id"] == "A"
    assert compute_draft_status(solo, 2, _picks(2))["is_complete"] is True


def test_validate_draft_order_accepts_a_clean_permutation():
    validate_draft_order(["A", "B", "C"], {"A", "B", "C"})  # no exception


def test_validate_draft_order_rejects_duplicates():
    with pytest.raises(ValueError):
        validate_draft_order(["A", "A", "B"], {"A", "B"})


def test_validate_draft_order_rejects_missing_participant():
    with pytest.raises(ValueError):
        validate_draft_order(["A"], {"A", "B"})


def test_validate_draft_order_rejects_unknown_participant():
    with pytest.raises(ValueError):
        validate_draft_order(["A", "Z"], {"A", "B"})


def test_validate_draft_order_rejects_empty():
    with pytest.raises(ValueError):
        validate_draft_order([], {"A"})


FANTASY_STATS = {
    "Lando Norris": {"total": 891.0, "average": 37.1},
    "Max Verstappen": {"total": 879.0, "average": 36.6},
    "Oscar Piastri": {"total": 869.0, "average": 36.2},
}


def test_sort_by_fantasy_points_ranks_highest_total_first():
    drivers = [
        {"id": "3", "full_name": "Oscar Piastri"},
        {"id": "1", "full_name": "Lando Norris"},
        {"id": "2", "full_name": "Max Verstappen"},
    ]

    sorted_drivers = _sort_by_fantasy_points(drivers, FANTASY_STATS)

    assert [d["full_name"] for d in sorted_drivers] == [
        "Lando Norris",
        "Max Verstappen",
        "Oscar Piastri",
    ]


def test_sort_by_fantasy_points_attaches_2025_fantasy_points():
    drivers = [{"id": "1", "full_name": "Lando Norris"}]

    sorted_drivers = _sort_by_fantasy_points(drivers, FANTASY_STATS)

    assert sorted_drivers[0]["fantasy_points_2025"] == 891.0
    assert sorted_drivers[0]["avg_fantasy_points_2025"] == 37.1


def test_sort_by_fantasy_points_puts_unranked_drivers_last_alphabetically():
    drivers = [
        {"id": "1", "full_name": "Lando Norris"},
        {"id": "2", "full_name": "Rookie Zeta"},
        {"id": "3", "full_name": "Rookie Alpha"},
    ]

    sorted_drivers = _sort_by_fantasy_points(drivers, FANTASY_STATS)

    assert [d["full_name"] for d in sorted_drivers] == [
        "Lando Norris",
        "Rookie Alpha",
        "Rookie Zeta",
    ]
    assert sorted_drivers[0]["fantasy_points_2025"] == 891.0
    assert sorted_drivers[1]["fantasy_points_2025"] is None
    assert sorted_drivers[2]["fantasy_points_2025"] is None
    assert sorted_drivers[1]["avg_fantasy_points_2025"] is None


def test_logo_url_for_known_team():
    assert logo_url_for_team("Ferrari") == "/static/img/constructors/ferrari.png"
    assert logo_url_for_team("Alpine F1 Team") == "/static/img/constructors/alpine.png"


def test_logo_url_for_unknown_team_is_none():
    assert logo_url_for_team("Some New Team") is None


def test_compute_seconds_remaining_counts_down():
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    now = started + timedelta(seconds=10)
    assert compute_seconds_remaining(started, now) == PICK_TIMER_SECONDS - 10


def test_compute_seconds_remaining_floors_at_zero():
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    now = started + timedelta(seconds=PICK_TIMER_SECONDS + 45)
    assert compute_seconds_remaining(started, now) == 0.0


def test_is_pick_expired_false_before_timer_elapses():
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    now = started + timedelta(seconds=PICK_TIMER_SECONDS - 1)
    assert is_pick_expired(started, now) is False


def test_is_pick_expired_true_once_timer_elapses():
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    now = started + timedelta(seconds=PICK_TIMER_SECONDS)
    assert is_pick_expired(started, now) is True


def test_get_turn_started_at_uses_launched_at_before_any_picks():
    state = {"launched_at": "2026-01-01T12:00:00+00:00"}
    assert get_turn_started_at(state, []) == datetime(
        2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc
    )


def test_get_turn_started_at_uses_most_recent_pick():
    state = {"launched_at": "2026-01-01T12:00:00+00:00"}
    picks = [
        {"picked_at": "2026-01-01T12:00:05+00:00"},
        {"picked_at": "2026-01-01T12:00:40+00:00"},
    ]
    assert get_turn_started_at(state, picks) == datetime(
        2026, 1, 1, 12, 0, 40, tzinfo=timezone.utc
    )
