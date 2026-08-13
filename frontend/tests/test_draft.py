from datetime import datetime, timedelta, timezone

import pytest

from app.services.draft import (
    EASTER_EGG_CELEBRATIONS,
    INTRO_DURATION_SECONDS,
    PICK_TIMER_SECONDS,
    VERSTAPPEN_CELEBRATION_SECONDS,
    _sort_by_fantasy_points,
    celebration_seconds_for_last_pick,
    compute_draft_countdown,
    compute_draft_status,
    compute_seconds_remaining,
    format_draft_scheduled_at_local,
    get_celebration_progress,
    get_intro_progress,
    get_turn_started_at,
    is_pick_expired,
    logo_url_for_team,
    parse_draft_scheduled_at,
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


def test_get_turn_started_at_offsets_first_pick_by_intro_seconds():
    state = {"launched_at": "2026-01-01T12:00:00+00:00"}
    assert get_turn_started_at(state, [], intro_seconds=60) == datetime(
        2026, 1, 1, 12, 1, 0, tzinfo=timezone.utc
    )


def test_get_turn_started_at_ignores_intro_seconds_once_picks_exist():
    state = {"launched_at": "2026-01-01T12:00:00+00:00"}
    picks = [{"picked_at": "2026-01-01T12:00:05+00:00"}]
    assert get_turn_started_at(state, picks, intro_seconds=60) == datetime(
        2026, 1, 1, 12, 0, 5, tzinfo=timezone.utc
    )


def test_get_intro_progress_counts_down():
    state = {"launched_at": "2026-01-01T12:00:00+00:00"}
    now = datetime(2026, 1, 1, 12, 0, 10, tzinfo=timezone.utc)
    elapsed, remaining = get_intro_progress(state, now)
    assert elapsed == 10
    assert remaining == INTRO_DURATION_SECONDS - 10


def test_get_intro_progress_clamps_to_the_intro_window():
    state = {"launched_at": "2026-01-01T12:00:00+00:00"}
    now = datetime(2026, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
    elapsed, remaining = get_intro_progress(state, now)
    assert elapsed == INTRO_DURATION_SECONDS
    assert remaining == 0


def _pick(driver_name, picked_at="2026-01-01T12:00:00+00:00"):
    return {"picked_at": picked_at, "f1_drivers": {"full_name": driver_name}}


def test_celebration_seconds_for_last_pick_is_zero_when_empty():
    assert celebration_seconds_for_last_pick([]) == 0


def test_celebration_seconds_for_last_pick_is_zero_for_other_drivers():
    # Fictional names — every real 2026 driver now has a celebration
    # clip, so a genuinely "not an easter egg" example has to be made up.
    picks = [_pick("Nobody Special"), _pick("Also Nobody")]
    assert celebration_seconds_for_last_pick(picks) == 0


def test_celebration_seconds_for_last_pick_only_looks_at_the_most_recent_pick():
    picks = [_pick("Max Verstappen"), _pick("Nobody Special")]
    assert celebration_seconds_for_last_pick(picks) == 0


def test_celebration_seconds_for_last_pick_fires_on_verstappen():
    picks = [_pick("Nobody Special"), _pick("Max Verstappen")]
    assert celebration_seconds_for_last_pick(picks) == VERSTAPPEN_CELEBRATION_SECONDS


def test_celebration_seconds_for_last_pick_fires_on_leclerc():
    picks = [_pick("Nobody Special"), _pick("Charles Leclerc")]
    assert celebration_seconds_for_last_pick(picks) == EASTER_EGG_CELEBRATIONS["Charles Leclerc"]


@pytest.mark.parametrize(
    "driver_name",
    [
        "Fernando Alonso",
        "Lewis Hamilton",
        "Nico Hülkenberg",
        "Lando Norris",
        "Sergio Pérez",
        "Oscar Piastri",
        "Lance Stroll",
        "Andrea Kimi Antonelli",
        "George Russell",
        "Liam Lawson",
        "Isack Hadjar",
        "Carlos Sainz",
        "Valtteri Bottas",
        "Oliver Bearman",
        "Franco Colapinto",
        "Arvid Lindblad",
        "Pierre Gasly",
        "Esteban Ocon",
        "Gabriel Bortoleto",
        "Alexander Albon",
    ],
)
def test_celebration_seconds_for_last_pick_fires_on_every_easter_egg_driver(driver_name):
    picks = [_pick("Nobody Special"), _pick(driver_name)]
    assert celebration_seconds_for_last_pick(picks) == EASTER_EGG_CELEBRATIONS[driver_name]


def test_get_celebration_progress_counts_down():
    picks = [_pick("Max Verstappen", picked_at="2026-01-01T12:00:00+00:00")]
    now = datetime(2026, 1, 1, 12, 0, 3, tzinfo=timezone.utc)
    elapsed, remaining = get_celebration_progress(picks, now)
    assert elapsed == 3
    assert remaining == VERSTAPPEN_CELEBRATION_SECONDS - 3


def test_get_celebration_progress_is_zero_for_other_drivers():
    picks = [_pick("Nobody Special")]
    now = datetime(2026, 1, 1, 12, 0, 3, tzinfo=timezone.utc)
    assert get_celebration_progress(picks, now) == (0.0, 0.0)


def test_compute_draft_countdown_breaks_down_days_hours_minutes():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    scheduled_at = now + timedelta(days=2, hours=3, minutes=25)
    assert compute_draft_countdown(scheduled_at, now) == {
        "total_seconds": (2 * 86400) + (3 * 3600) + (25 * 60),
        "days": 2,
        "hours": 3,
        "minutes": 25,
    }


def test_compute_draft_countdown_under_a_day():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    scheduled_at = now + timedelta(hours=5, minutes=10)
    countdown = compute_draft_countdown(scheduled_at, now)
    assert countdown["days"] == 0
    assert countdown["hours"] == 5
    assert countdown["minutes"] == 10


def test_compute_draft_countdown_clamps_at_zero_once_passed():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    scheduled_at = now - timedelta(hours=1)
    assert compute_draft_countdown(scheduled_at, now) == {
        "total_seconds": 0,
        "days": 0,
        "hours": 0,
        "minutes": 0,
    }


def test_parse_draft_scheduled_at_converts_eastern_to_utc():
    # Mid-January — solidly outside any DST transition window, so EST
    # (UTC-5) applies unambiguously.
    assert parse_draft_scheduled_at("2026-01-15T19:00") == "2026-01-16T00:00:00+00:00"


def test_format_draft_scheduled_at_local_round_trips_parse():
    local_value = "2026-01-15T19:00"
    assert format_draft_scheduled_at_local(parse_draft_scheduled_at(local_value)) == local_value


def test_get_turn_started_at_offsets_by_celebration_seconds():
    state = {"launched_at": "2026-01-01T12:00:00+00:00"}
    picks = [_pick("Max Verstappen", picked_at="2026-01-01T12:00:05+00:00")]
    assert get_turn_started_at(state, picks, celebration_seconds=8) == datetime(
        2026, 1, 1, 12, 0, 13, tzinfo=timezone.utc
    )
