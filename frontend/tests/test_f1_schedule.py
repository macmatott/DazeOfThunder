"""
get_upcoming_races filter/sort logic, tested against the JolpicaClient
boundary (get_full_schedule mocked) rather than the network.
"""

from datetime import datetime, timezone
from unittest.mock import patch

from app.services.f1_schedule import get_upcoming_races

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
