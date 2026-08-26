"""
get_upcoming_races filter/sort logic, tested against the JolpicaClient
boundary (get_full_schedule mocked) rather than the network.
"""

from datetime import date, datetime, timezone
from unittest.mock import patch

from app.services.f1_schedule import (
    IRACING_TRACK_BY_ROUND,
    SIM_CONDITIONS,
    SIM_CONDITIONS_BY_ROUND,
    SIM_TEMPERATURE_BY_ROUND,
    SIM_TEMPERATURE_F,
    _group_results_by_round,
    _merge_schedule_with_results,
    _thursday_before,
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


def test_thursday_before_sunday_race():
    # 2026-03-08 is a Sunday; the Thursday before it is 2026-03-05.
    race_dt = datetime(2026, 3, 8, 4, 0, tzinfo=timezone.utc)
    assert _thursday_before(race_dt) == date(2026, 3, 5)


def test_thursday_before_race_already_on_thursday():
    race_dt = datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)
    assert _thursday_before(race_dt) == date(2026, 3, 5)


def test_merge_attaches_sim_placeholder_fields_to_every_race():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    races = _merge_schedule_with_results(SCHEDULE, {}, now)

    by_round = {r["round_number"]: r for r in races}
    assert by_round[1]["sim_date"] == "Mar 5, 2026"
    assert by_round[2]["sim_date"] == "Mar 19, 2026"
    assert by_round[3]["sim_date"] == "Apr 2, 2026"
    assert by_round[1]["sim_temperature_f"] == SIM_TEMPERATURE_BY_ROUND[1]
    assert by_round[2]["sim_temperature_f"] == SIM_TEMPERATURE_BY_ROUND[2]
    for race in races:
        assert "sim_temperature_f" in race
        assert "sim_conditions" in race


def test_merge_attaches_iracing_track_by_round():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    races = _merge_schedule_with_results(SCHEDULE, {}, now)

    by_round = {r["round_number"]: r for r in races}
    assert by_round[1]["iracing_track"] == IRACING_TRACK_BY_ROUND[1]
    assert by_round[2]["iracing_track"] == IRACING_TRACK_BY_ROUND[2]
    assert by_round[3]["iracing_track"] == IRACING_TRACK_BY_ROUND[3]


def test_merge_iracing_track_is_none_for_unmapped_round():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    unmapped_schedule = [{**SCHEDULE[0], "round": "99"}]

    races = _merge_schedule_with_results(unmapped_schedule, {}, now)

    assert races[0]["iracing_track"] is None


def test_merge_defaults_iracing_track_is_paid_to_false():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    races = _merge_schedule_with_results(SCHEDULE, {}, now)

    assert all(race["iracing_track_is_paid"] is False for race in races)


def test_merge_marks_iracing_track_is_paid_when_name_matches():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    # Round 1 -> "Phillip Island Circuit" (no " — config" suffix).
    races = _merge_schedule_with_results(SCHEDULE, {}, now, {"Phillip Island Circuit"})

    by_round = {r["round_number"]: r for r in races}
    assert by_round[1]["iracing_track_is_paid"] is True
    assert by_round[2]["iracing_track_is_paid"] is False


def test_merge_matches_paid_track_names_against_the_base_name_only():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    # Round 2 -> "Okayama International Circuit — Full Course" — the paid
    # set is keyed by track identity, not the round's specific config, so
    # the bare name (no " — config" suffix) must still match.
    races = _merge_schedule_with_results(
        SCHEDULE, {}, now, {"Okayama International Circuit"}
    )

    by_round = {r["round_number"]: r for r in races}
    assert by_round[2]["iracing_track_is_paid"] is True


def test_merge_attaches_iso_f1_date():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    races = _merge_schedule_with_results(SCHEDULE, {}, now)

    by_round = {r["round_number"]: r for r in races}
    assert by_round[1]["race_date_iso"] == "2026-03-08"
    assert by_round[2]["race_date_iso"] == "2026-03-22"
    assert by_round[3]["race_date_iso"] == "2026-04-05"


def test_merge_uses_per_round_sim_weather_override():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    round_7 = {**SCHEDULE[0], "round": "7"}

    races = _merge_schedule_with_results([round_7], {}, now)

    assert races[0]["sim_temperature_f"] == SIM_TEMPERATURE_BY_ROUND[7]
    assert races[0]["sim_temperature_f"] == 75
    assert races[0]["sim_conditions"] == SIM_CONDITIONS_BY_ROUND[7]


def test_merge_falls_back_to_default_weather_for_unlisted_round():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    unmapped_round = {**SCHEDULE[0], "round": "99"}

    races = _merge_schedule_with_results([unmapped_round], {}, now)

    assert races[0]["sim_temperature_f"] == SIM_TEMPERATURE_F
    assert races[0]["sim_conditions"] == SIM_CONDITIONS


def test_merge_defaults_sim_session_detail_to_none_with_no_real_import():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    races = _merge_schedule_with_results(SCHEDULE, {}, now)

    for race in races:
        assert race["sim_session_detail"] is None


def test_merge_attaches_sim_session_detail_only_for_rounds_with_a_real_import():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    sim_session_details = {1: {"track": "Phillip Island Circuit", "results": []}}
    races = _merge_schedule_with_results(SCHEDULE, {}, now, sim_session_details=sim_session_details)

    by_round = {r["round_number"]: r for r in races}
    assert by_round[1]["sim_session_detail"] == {"track": "Phillip Island Circuit", "results": []}
    assert by_round[2]["sim_session_detail"] is None
