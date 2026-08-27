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
    _merge_schedule_with_results,
    _parse_lap_time_seconds,
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


def test_merge_marks_past_next_and_future():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)  # after round 1, before 2 & 3

    races = _merge_schedule_with_results(SCHEDULE, now)

    by_round = {r["round_number"]: r for r in races}

    assert by_round[1]["is_past"] is True
    assert by_round[1]["is_next"] is False

    assert by_round[2]["is_past"] is False
    assert by_round[2]["is_next"] is True

    assert by_round[3]["is_past"] is False
    assert by_round[3]["is_next"] is False


def test_thursday_before_sunday_race():
    # 2026-03-08 is a Sunday; the Thursday before it is 2026-03-05.
    race_dt = datetime(2026, 3, 8, 4, 0, tzinfo=timezone.utc)
    assert _thursday_before(race_dt) == date(2026, 3, 5)


def test_thursday_before_race_already_on_thursday():
    race_dt = datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)
    assert _thursday_before(race_dt) == date(2026, 3, 5)


def test_merge_attaches_sim_placeholder_fields_to_every_race():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    races = _merge_schedule_with_results(SCHEDULE, now)

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
    races = _merge_schedule_with_results(SCHEDULE, now)

    by_round = {r["round_number"]: r for r in races}
    assert by_round[1]["iracing_track"] == IRACING_TRACK_BY_ROUND[1]
    assert by_round[2]["iracing_track"] == IRACING_TRACK_BY_ROUND[2]
    assert by_round[3]["iracing_track"] == IRACING_TRACK_BY_ROUND[3]


def test_merge_iracing_track_is_none_for_unmapped_round():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    unmapped_schedule = [{**SCHEDULE[0], "round": "99"}]

    races = _merge_schedule_with_results(unmapped_schedule, now)

    assert races[0]["iracing_track"] is None


def test_merge_defaults_iracing_track_is_paid_to_false():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    races = _merge_schedule_with_results(SCHEDULE, now)

    assert all(race["iracing_track_is_paid"] is False for race in races)


def test_merge_marks_iracing_track_is_paid_when_name_matches():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    # Round 1 -> "Phillip Island Circuit" (no " — config" suffix).
    races = _merge_schedule_with_results(SCHEDULE, now, {"Phillip Island Circuit"})

    by_round = {r["round_number"]: r for r in races}
    assert by_round[1]["iracing_track_is_paid"] is True
    assert by_round[2]["iracing_track_is_paid"] is False


def test_merge_matches_paid_track_names_against_the_base_name_only():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    # Round 2 -> "Okayama International Circuit — Full Course" — the paid
    # set is keyed by track identity, not the round's specific config, so
    # the bare name (no " — config" suffix) must still match.
    races = _merge_schedule_with_results(
        SCHEDULE, now, {"Okayama International Circuit"}
    )

    by_round = {r["round_number"]: r for r in races}
    assert by_round[2]["iracing_track_is_paid"] is True


def test_merge_attaches_iso_f1_date():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    races = _merge_schedule_with_results(SCHEDULE, now)

    by_round = {r["round_number"]: r for r in races}
    assert by_round[1]["race_date_iso"] == "2026-03-08"
    assert by_round[2]["race_date_iso"] == "2026-03-22"
    assert by_round[3]["race_date_iso"] == "2026-04-05"


def test_merge_uses_per_round_sim_weather_override():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    round_7 = {**SCHEDULE[0], "round": "7"}

    races = _merge_schedule_with_results([round_7], now)

    assert races[0]["sim_temperature_f"] == SIM_TEMPERATURE_BY_ROUND[7]
    assert races[0]["sim_temperature_f"] == 75
    assert races[0]["sim_conditions"] == SIM_CONDITIONS_BY_ROUND[7]


def test_merge_falls_back_to_default_weather_for_unlisted_round():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    unmapped_round = {**SCHEDULE[0], "round": "99"}

    races = _merge_schedule_with_results([unmapped_round], now)

    assert races[0]["sim_temperature_f"] == SIM_TEMPERATURE_F
    assert races[0]["sim_conditions"] == SIM_CONDITIONS


def test_merge_defaults_sim_session_detail_to_none_with_no_real_import():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    races = _merge_schedule_with_results(SCHEDULE, now)

    for race in races:
        assert race["sim_session_detail"] is None


def test_merge_attaches_sim_session_detail_only_for_rounds_with_a_real_import():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    sim_session_details = {1: {"track": "Phillip Island Circuit", "results": []}}
    races = _merge_schedule_with_results(SCHEDULE, now, sim_session_details=sim_session_details)

    by_round = {r["round_number"]: r for r in races}
    assert by_round[1]["sim_session_detail"] == {"track": "Phillip Island Circuit", "results": []}
    assert by_round[2]["sim_session_detail"] is None


def test_merge_defaults_f1_session_detail_to_none_with_no_real_import():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    races = _merge_schedule_with_results(SCHEDULE, now)

    for race in races:
        assert race["f1_session_detail"] is None


def test_merge_attaches_f1_session_detail_only_for_rounds_with_a_real_import():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    f1_session_details = {1: {"results": [{"driver_name": "Lando Norris"}]}}
    races = _merge_schedule_with_results(SCHEDULE, now, f1_session_details=f1_session_details)

    by_round = {r["round_number"]: r for r in races}
    assert by_round[1]["f1_session_detail"] == {"results": [{"driver_name": "Lando Norris"}]}


def test_merge_defaults_f1_sprint_session_detail_to_none_with_no_real_import():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    races = _merge_schedule_with_results(SCHEDULE, now)

    for race in races:
        assert race["f1_sprint_session_detail"] is None


def test_merge_attaches_f1_sprint_session_detail_only_for_rounds_with_a_real_import():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    f1_sprint_session_details = {1: {"results": [{"driver_name": "Max Verstappen"}]}}
    races = _merge_schedule_with_results(
        SCHEDULE, now, f1_sprint_session_details=f1_sprint_session_details
    )

    by_round = {r["round_number"]: r for r in races}
    assert by_round[1]["f1_sprint_session_detail"] == {"results": [{"driver_name": "Max Verstappen"}]}
    assert by_round[2]["f1_sprint_session_detail"] is None
    assert by_round[2]["f1_session_detail"] is None


def test_parse_lap_time_seconds_handles_minutes_and_seconds():
    assert _parse_lap_time_seconds("1:35.381") == 95.381


def test_parse_lap_time_seconds_handles_bare_seconds():
    assert _parse_lap_time_seconds("35.381") == 35.381


def test_parse_lap_time_seconds_is_none_for_missing_or_unparseable():
    assert _parse_lap_time_seconds(None) is None
    assert _parse_lap_time_seconds("") is None
    assert _parse_lap_time_seconds("DNF") is None
