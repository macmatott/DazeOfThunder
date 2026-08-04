"""
get_upcoming_races filter/sort logic, tested against the JolpicaClient
boundary (get_full_schedule mocked) rather than the network.
"""

from datetime import datetime, timezone
from unittest.mock import patch

from app.services.f1_schedule import (
    _group_results_by_round,
    _merge_schedule_with_results,
    get_upcoming_races,
)

SCHEDULE = [
    {
        "round": "1",
        "raceName": "Australian Grand Prix",
        "Circuit": {
            "circuitName": "Albert Park Grand Prix Circuit",
            "Location": {"locality": "Melbourne", "country": "Australia"},
        },
        "date": "2026-03-08",
        "time": "04:00:00Z",
    },
    {
        "round": "2",
        "raceName": "Chinese Grand Prix",
        "Circuit": {
            "circuitName": "Shanghai International Circuit",
            "Location": {"locality": "Shanghai", "country": "China"},
        },
        "date": "2026-03-22",
        "time": "07:00:00Z",
    },
    {
        # No `time` field — some far-future rounds omit it.
        "round": "3",
        "raceName": "Japanese Grand Prix",
        "Circuit": {
            "circuitName": "Suzuka Circuit",
            "Location": {"locality": "Suzuka", "country": "Japan"},
        },
        "date": "2026-04-05",
    },
]


def test_excludes_past_races_and_sorts_ascending():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)  # after round 1, before 2 & 3
    with patch(
        "app.services.f1_schedule.JolpicaClient.get_full_schedule",
        return_value=SCHEDULE,
    ):
        races = get_upcoming_races(2026, now=now)

    assert [r["round_number"] for r in races] == [2, 3]
    assert races[0]["race_name"] == "Chinese Grand Prix"
    assert races[0]["location"] == "Shanghai, China"


def test_handles_missing_time_field():
    now = datetime(2026, 4, 1, tzinfo=timezone.utc)
    with patch(
        "app.services.f1_schedule.JolpicaClient.get_full_schedule",
        return_value=SCHEDULE,
    ):
        races = get_upcoming_races(2026, now=now)

    assert [r["round_number"] for r in races] == [3]
    assert races[0]["race_name"] == "Japanese Grand Prix"


RESULT_ROWS = [
    {
        "round_number": 1,
        "finish_position": 2,
        "points": 18.0,
        "status": "Finished",
        "f1_drivers": {"full_name": "Max Verstappen", "team_name": "Red Bull"},
    },
    {
        "round_number": 1,
        "finish_position": 1,
        "points": 25.0,
        "status": "Finished",
        "f1_drivers": {"full_name": "Lando Norris", "team_name": "McLaren"},
    },
]


def test_group_results_by_round_groups_and_preserves_row_order():
    grouped = _group_results_by_round(RESULT_ROWS)

    assert list(grouped.keys()) == [1]
    assert [r["driver_name"] for r in grouped[1]] == ["Max Verstappen", "Lando Norris"]
    assert grouped[1][1]["points"] == 25.0
    assert grouped[1][1]["team_name"] == "McLaren"


def test_merge_marks_past_next_and_future_and_attaches_results():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)  # after round 1, before 2 & 3
    results_by_round = _group_results_by_round(RESULT_ROWS)

    races = _merge_schedule_with_results(SCHEDULE, results_by_round, now)

    by_round = {r["round_number"]: r for r in races}

    assert by_round[1]["is_past"] is True
    assert by_round[1]["is_next"] is False
    assert [r["driver_name"] for r in by_round[1]["results"]] == [
        "Max Verstappen",
        "Lando Norris",
    ]

    assert by_round[2]["is_past"] is False
    assert by_round[2]["is_next"] is True
    assert by_round[2]["results"] is None

    assert by_round[3]["is_past"] is False
    assert by_round[3]["is_next"] is False
    assert by_round[3]["results"] is None


def test_merge_past_round_with_no_imported_results_is_empty_not_missing():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)

    races = _merge_schedule_with_results(SCHEDULE, {}, now)

    by_round = {r["round_number"]: r for r in races}
    assert by_round[1]["is_past"] is True
    assert by_round[1]["results"] == []
