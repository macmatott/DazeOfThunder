"""
Pure-function tests for iRacing JSON parsing — run against real
exports (discord-bot/tests/fixtures/), per that fixture directory's own
README: build and test against an actual export, not an assumed
format. No network, no Supabase.

Three real fixtures, three different shapes:
- eventresult-88113080.json: a Hosted session (this league's actual
  weekly race format) — solo drivers, no official-series season/week/
  strength-of-field metadata of its own.
- eventresult-87103907.json: an official series (24 Hours of Spa) —
  real season metadata, and a TEAM race (one car per result, a nested
  driver_results list per co-driver rather than a flat cust_id row).
- eventresult-87448524.json: another official series team race, and
  multiclass (GTP/Dallara P217/IMSA23) — exercises Team Events' own
  per-class ranking against something genuinely multiclass.
"""

import json
from pathlib import Path

import pytest

from app.services.iracing_ingest import (
    JsonParseError,
    _format_interval,
    _ticks_to_time_str,
    compute_sim_scores,
    match_participants,
    parse_event_json,
)

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "discord-bot" / "tests" / "fixtures"
FIXTURE_PATH = FIXTURE_DIR / "eventresult-88113080.json"
TEAM_FIXTURE_PATH = FIXTURE_DIR / "eventresult-87103907.json"
MULTICLASS_TEAM_FIXTURE_PATH = FIXTURE_DIR / "eventresult-87448524.json"


def _fixture_bytes() -> bytes:
    return FIXTURE_PATH.read_bytes()


def test_ticks_to_time_str_truncates_not_rounds():
    # 987708 ten-thousandths -> 98.7708s. iRacing's own CSV export for
    # this exact driver/race truncates to "1:38.770", not the correctly
    # rounded "1:38.771" — matched here rather than silently disagreeing
    # with it on the last digit.
    assert _ticks_to_time_str(987708) == "1:38.770"


def test_ticks_to_time_str_under_a_minute_has_no_minutes_prefix():
    assert _ticks_to_time_str(347662) == "34.766"


def test_ticks_to_time_str_none_for_missing_or_negative():
    assert _ticks_to_time_str(None) is None
    assert _ticks_to_time_str(-1) is None


def test_format_interval_leader_is_dash_zero():
    assert _format_interval(0, leader_laps=36, driver_laps=36) == "-00.000"


def test_format_interval_gap_under_a_minute():
    assert _format_interval(347662, leader_laps=36, driver_laps=36) == "-34.766"


def test_format_interval_gap_over_a_minute():
    assert _format_interval(721251, leader_laps=36, driver_laps=36) == "-1:12.125"


def test_format_interval_lapped_computes_laps_down():
    # -1 is iRacing's sentinel for "not on the lead lap" — no gap time,
    # so it's expressed as a lap-down count instead, same convention the
    # CSV export uses ("-25 L" for this exact driver/race).
    assert _format_interval(-1, leader_laps=36, driver_laps=11) == "-25 L"


def test_parse_event_json_against_real_hosted_fixture_event_block():
    parsed = parse_event_json(_fixture_bytes())
    assert parsed["event"] == {
        "iracing_event_id": 88113080,
        "track": "Circuit Zandvoort - Grand Prix",
        "series": "Hosted iRacing",
        "start_time": "2026-08-21T00:30:40Z",
        # Hosted sessions report placeholder season/week metadata
        # (season_id 0), nulled out to match the CSV export's behavior
        # of not having these columns at all for a Hosted race.
        "iracing_season_year": None,
        "iracing_season_quarter": None,
        "race_week": None,
        # Real, unlike the CSV export — a Hosted-session CSV simply
        # never has a Strength of Field column, not because the data
        # doesn't exist.
        "strength_of_field": 1323,
        "special_event_type": None,
        # This event has only one split, so there's nothing to report.
        "split_number": None,
        "split_total": None,
    }
    assert len(parsed["results"]) == 10


def test_parse_event_json_maps_full_winner_row():
    parsed = parse_event_json(_fixture_bytes())
    winner = parsed["results"][0]
    assert winner == {
        "finish_position": 1,
        "iracing_cust_id": 1493105,
        "iracing_display_name": "Mac Matott",
        "start_position": 1,
        "car_name": "FIA F4",
        "car_class": "Hosted All Cars Class",
        "car_class_id": 0,
        "car_number": "6",
        "status": "Running",
        "interval": "-00.000",
        "laps_led": 35,
        "laps_completed": 36,
        "incidents": 4,
        # Real, unlike the CSV export — its own Qualify Time column is
        # blank for every driver in this exact real race despite real
        # qualifying laps having actually happened.
        "qualify_time": "1:34.962",
        "average_lap_time": "1:37.805",
        "fastest_lap_time": "1:35.381",
        "fastest_lap_number": 16,
        # Real, unlike the CSV export (a Hosted-session CSV never has
        # Pts/Old iRating/New iRating columns) — kept for future use.
        "iracing_points": 22,
        "iracing_club_points": None,
        "old_irating": 2143,
        "new_irating": 2143,
        "is_ai": False,
    }


def test_parse_event_json_lapped_and_disconnected_driver():
    parsed = parse_event_json(_fixture_bytes())
    last = parsed["results"][-1]  # Dylan Stowe — disconnected, 25 laps down
    assert last["iracing_display_name"] == "Dylan Stowe2"
    assert last["status"] == "Disconnected"
    assert last["interval"] == "-25 L"
    assert last["laps_completed"] == 11
    assert last["qualify_time"] is None  # never set a qualifying lap
    assert last["fastest_lap_time"] == "1:41.441"
    assert last["fastest_lap_number"] == 5


def test_parse_event_json_qualify_time_none_when_driver_never_qualified():
    # Mitchell Davies finished P2 in the race but never set a qualifying
    # lap (best_qual_lap_time -1 in the Lone Qualifying session) — the
    # cross-session lookup must fall back to None, not error.
    parsed = parse_event_json(_fixture_bytes())
    mitchell = next(r for r in parsed["results"] if r["iracing_cust_id"] == 889883)
    assert mitchell["finish_position"] == 2
    assert mitchell["qualify_time"] is None


def test_parse_event_json_rejects_non_event_result_payload():
    with pytest.raises(JsonParseError):
        parse_event_json(json.dumps({"type": "something_else", "data": {}}).encode())


def test_parse_event_json_rejects_invalid_json():
    with pytest.raises(JsonParseError):
        parse_event_json(b"not json at all")


def test_parse_event_json_rejects_missing_race_session():
    payload = {
        "type": "event_result",
        "data": {
            "subsession_id": 1,
            "track": {"track_name": "Test", "config_name": "GP"},
            "series_name": "Hosted iRacing",
            "start_time": "2026-01-01T00:00:00Z",
            "season_id": 0,
            "session_results": [{"simsession_type": 4, "results": []}],
        },
    }
    with pytest.raises(JsonParseError):
        parse_event_json(json.dumps(payload).encode())


def test_parse_event_json_official_series_keeps_real_season_metadata():
    parsed = parse_event_json(TEAM_FIXTURE_PATH.read_bytes())
    assert parsed["event"]["track"] == "Circuit de Spa-Francorchamps - Endurance"
    assert parsed["event"]["iracing_season_year"] == 2026
    assert parsed["event"]["iracing_season_quarter"] == 3
    assert parsed["event"]["race_week"] == 0
    assert parsed["event"]["strength_of_field"] == 1439


def test_parse_event_json_computes_which_split_we_raced():
    # A 24-hour enduro is too big for one session, so it's split into
    # several parallel fields — our subsession's 1-indexed position
    # among all of them (strongest field first) is "our split".
    parsed = parse_event_json(TEAM_FIXTURE_PATH.read_bytes())
    assert parsed["event"]["split_number"] == 11
    assert parsed["event"]["split_total"] == 13


def test_parse_event_json_computes_split_for_a_different_multiclass_race():
    parsed = parse_event_json(MULTICLASS_TEAM_FIXTURE_PATH.read_bytes())
    assert parsed["event"]["split_number"] == 9
    assert parsed["event"]["split_total"] == 11


def test_parse_event_json_flattens_team_race_into_one_row_per_co_driver():
    # A team race's session results are keyed by team_id (one entry per
    # car) with a nested driver_results list, not a flat per-cust_id
    # row like a solo race — this is the winning car's 4-driver crew,
    # all sharing the car's finish_position/interval/car_number but
    # each with their own cust_id/incidents.
    parsed = parse_event_json(TEAM_FIXTURE_PATH.read_bytes())
    winners = [r for r in parsed["results"] if r["finish_position"] == 1]

    assert len(winners) == 4
    assert {w["iracing_display_name"] for w in winners} == {
        "Travis McQuistion",
        "Gael Brooks",
        "Django Matthews",
        "Don Runkle Jr",
    }
    assert all(w["interval"] == "-00.000" for w in winners)
    assert all(w["car_number"] == "93" for w in winners)
    # Per-driver stats aren't just copied from the car — each co-driver
    # has their own incident count.
    assert len({w["incidents"] for w in winners}) > 1


def test_parse_event_json_multiclass_team_race_car_classes():
    parsed = parse_event_json(MULTICLASS_TEAM_FIXTURE_PATH.read_bytes())
    car_classes = {r["car_class"] for r in parsed["results"]}
    assert car_classes == {"GTP", "Dallara P217", "IMSA23"}


def test_match_participants_maps_by_cust_id_and_leaves_unmatched_as_none():
    results = [
        {"iracing_cust_id": 111, "finish_position": 1},
        {"iracing_cust_id": 222, "finish_position": 2},
    ]
    matched = match_participants(results, {111: "participant-a"})
    assert matched[0]["participant_id"] == "participant-a"
    assert matched[1]["participant_id"] is None


def test_compute_sim_scores_excludes_unmatched_and_ai_rows():
    results = [
        {"participant_id": "participant-a", "finish_position": 1, "is_ai": False},
        {"participant_id": None, "finish_position": 2, "is_ai": False},
        {"participant_id": "participant-b", "finish_position": 3, "is_ai": True},
    ]
    points_table = {1: 10.0, 2: 8.0, 3: 7.0}
    scores = compute_sim_scores(results, points_table)
    assert scores == [{"participant_id": "participant-a", "points": 10.0}]
