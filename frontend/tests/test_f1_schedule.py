"""
get_upcoming_races filter/sort logic, tested against the JolpicaClient
boundary (get_full_schedule mocked) rather than the network.
"""

from datetime import date, datetime, timezone
from unittest.mock import patch

from app.services.f1_schedule import (
    F1_LAPS_BY_ROUND,
    IRACING_TRACK_BY_ROUND,
    SIM_CONDITIONS,
    SIM_CONDITIONS_BY_ROUND,
    SIM_TEMPERATURE_BY_ROUND,
    SIM_TEMPERATURE_F,
    _group_results_by_round,
    _merge_schedule_with_results,
    _session_detail,
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


def test_session_detail_splits_track_name_and_config():
    detail = _session_detail(
        round_number=7,
        race_name="Barcelona Grand Prix",
        iracing_track="Circuit de Barcelona-Catalunya — Grand Prix",
        location="Barcelona, Spain",
        sim_date="Jun 11, 2026",
        sim_temperature_f=75,
        sim_conditions="No rain",
        is_past=True,
        results=[{"driver_name": "George Russell"}],
    )

    assert detail["track"]["name"] == "Circuit de Barcelona-Catalunya"
    assert detail["track"]["config"] == "Grand Prix"
    assert detail["track"]["venue"] == "Barcelona, Spain"


def test_session_detail_handles_track_with_no_config():
    detail = _session_detail(
        round_number=11,
        race_name="Hungarian Grand Prix",
        iracing_track="Hungaroring",
        location="Budapest, Hungary",
        sim_date="Jul 23, 2026",
        sim_temperature_f=71,
        sim_conditions="No rain",
        is_past=False,
        results=None,
    )

    assert detail["track"]["name"] == "Hungaroring"
    assert detail["track"]["config"] == "—"


def test_session_detail_status_and_has_results_reflect_past_vs_future():
    past = _session_detail(
        round_number=1,
        race_name="Australian Grand Prix",
        iracing_track="Phillip Island Circuit",
        location="Melbourne, Australia",
        sim_date="Mar 5, 2026",
        sim_temperature_f=72,
        sim_conditions="No rain",
        is_past=True,
        results=[{"driver_name": "George Russell"}],
    )
    future = _session_detail(
        round_number=12,
        race_name="Dutch Grand Prix",
        iracing_track="Circuit Park Zandvoort",
        location="Zandvoort, Netherlands",
        sim_date="Aug 20, 2026",
        sim_temperature_f=80,
        sim_conditions="No rain",
        is_past=False,
        results=None,
    )
    past_no_results_yet = _session_detail(
        round_number=2,
        race_name="Chinese Grand Prix",
        iracing_track="Okayama International Circuit — Full Course",
        location="Shanghai, China",
        sim_date="Mar 19, 2026",
        sim_temperature_f=66,
        sim_conditions="No rain",
        is_past=True,
        results=[],
    )

    assert past["session_meta"]["status"] == "Completed"
    assert past["session_meta"]["has_results"] == "Yes"

    assert future["session_meta"]["status"] == "Scheduled"
    assert future["session_meta"]["has_results"] == "No"

    assert past_no_results_yet["session_meta"]["status"] == "Completed"
    assert past_no_results_yet["session_meta"]["has_results"] == "No"


def test_session_detail_carries_real_weather_and_round_number():
    detail = _session_detail(
        round_number=9,
        race_name="British Grand Prix",
        iracing_track="Silverstone Circuit — Grand Prix",
        location="Silverstone, UK",
        sim_date="Jul 16, 2026",
        sim_temperature_f=67,
        sim_conditions="No rain",
        is_past=True,
        results=[],
    )

    assert detail["weather"]["temperature_f"] == 67
    assert detail["weather"]["precip_option"] == "No rain"
    assert detail["entries"]["race_number"] == 9
    assert detail["database"]["race_number"] == 9
    assert detail["database"]["race_name"] == "British Grand Prix"


def test_session_detail_computes_50pct_race_laps_rounding_down():
    detail = _session_detail(
        round_number=3,  # F1_LAPS_BY_ROUND[3] == 53 (odd)
        race_name="Japanese Grand Prix",
        iracing_track="Suzuka International Racing Course — Grand Prix",
        location="Suzuka, Japan",
        sim_date="Apr 2, 2026",
        sim_temperature_f=67,
        sim_conditions="No rain",
        is_past=True,
        results=[],
    )

    assert F1_LAPS_BY_ROUND[3] == 53
    assert detail["session_lengths"]["race"] == "26 laps"
    assert detail["session_lengths"]["race_laps"] == "26 laps (50% of 53)"


def test_session_detail_falls_back_when_round_has_no_lap_data():
    detail = _session_detail(
        round_number=99,
        race_name="Unmapped Grand Prix",
        iracing_track=None,
        location="Nowhere",
        sim_date="Jan 1, 2026",
        sim_temperature_f=80,
        sim_conditions="No rain",
        is_past=False,
        results=None,
    )

    assert detail["session_lengths"]["race"] == "50% GP"
    assert detail["session_lengths"]["race_laps"] == "—"


def test_merge_attaches_session_detail_to_every_race():
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    races = _merge_schedule_with_results(SCHEDULE, {}, now)

    for race in races:
        assert "session_detail" in race
        assert race["session_detail"]["track"]["venue"] == race["location"]
