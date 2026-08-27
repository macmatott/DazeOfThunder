"""
Pure mapping-function tests for the F1 ingestion adapter. No network, no
Supabase — payloads below are real Jolpica-F1 responses (2025 Australian GP)
captured verbatim.
"""

from app.services.f1_ingest import map_result_to_row, normalize_constructor_name

WINNER_RESULT = {
    "number": "4",
    "position": "1",
    "positionText": "1",
    "points": "25",
    "Driver": {
        "driverId": "norris",
        "permanentNumber": "1",
        "code": "NOR",
        "givenName": "Lando",
        "familyName": "Norris",
        "dateOfBirth": "1999-11-13",
        "nationality": "British",
    },
    "Constructor": {"constructorId": "mclaren", "name": "McLaren", "nationality": "British"},
    "grid": "1",
    "laps": "57",
    "status": "Finished",
    "Time": {"millis": "6126304", "time": "1:42:06.304"},
    "FastestLap": {"rank": "1", "lap": "43", "Time": {"time": "1:22.167"}},
}

DNF_RESULT = {
    "number": "30",
    "position": "15",
    "positionText": "R",
    "points": "0",
    "Driver": {
        "driverId": "lawson",
        "permanentNumber": "30",
        "code": "LAW",
        "givenName": "Liam",
        "familyName": "Lawson",
        "dateOfBirth": "2002-02-11",
        "nationality": "New Zealander",
    },
    "Constructor": {"constructorId": "red_bull", "name": "Red Bull", "nationality": "Austrian"},
    "grid": "18",
    "laps": "46",
    "status": "Retired",
    "FastestLap": {"rank": "2", "lap": "43", "Time": {"time": "1:23.500"}},
}


def test_maps_race_winner_with_fastest_lap():
    row = map_result_to_row(
        WINNER_RESULT,
        season_id="season-uuid",
        round_number=1,
        race_name="Australian Grand Prix",
        is_sprint=False,
        f1_driver_id="driver-uuid",
    )

    assert row == {
        "season_id": "season-uuid",
        "round_number": 1,
        "race_name": "Australian Grand Prix",
        "is_sprint": False,
        "f1_driver_id": "driver-uuid",
        "finish_position": 1,
        "status": "Finished",
        "points": 25.0,
        "fastest_lap": True,
        "car_number": 4,
        "start_position": 1,
        "interval": "1:42:06.304",
        "laps": 57,
        "fastest_lap_time": "1:22.167",
        "fastest_lap_number": 43,
    }


def test_maps_dnf_with_numeric_classification_position():
    row = map_result_to_row(
        DNF_RESULT,
        season_id="season-uuid",
        round_number=1,
        race_name="Australian Grand Prix",
        is_sprint=False,
        f1_driver_id="driver-uuid",
    )

    # position stays numeric (final classification order) even for DNFs;
    # the DNF itself is only visible via status/points.
    assert row["finish_position"] == 15
    assert row["status"] == "Retired"
    assert row["points"] == 0.0
    assert row["fastest_lap"] is False
    # A retired driver still has no classified race time/gap (no "Time"
    # key at all in the raw payload), even though laps/car number/fastest
    # lap are still reported.
    assert row["interval"] is None
    assert row["car_number"] == 30
    assert row["laps"] == 46
    assert row["fastest_lap_time"] == "1:23.500"


def test_normalize_constructor_name_corrects_stale_jolpica_names():
    # Jolpica/Ergast still returns these two teams' older/shorter names
    # (confirmed live) — normalized to current official branding so
    # f1_drivers.team_name matches the CONSTRUCTOR_LOGOS/celebration keys.
    assert normalize_constructor_name("Red Bull") == "Red Bull Racing"
    assert normalize_constructor_name("RB F1 Team") == "Racing Bulls"


def test_normalize_constructor_name_leaves_other_teams_unchanged():
    assert normalize_constructor_name("McLaren") == "McLaren"
