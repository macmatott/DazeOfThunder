"""
Pure-function tests for iRacing CSV parsing — run against a real export
(discord-bot/tests/fixtures/eventresult_87601875_0.csv), per that
fixture's own README: build and test against an actual export, not an
assumed format. No network, no Supabase.
"""

from pathlib import Path

import pytest

from app.services.iracing_ingest import (
    CsvParseError,
    InvalidFilenameError,
    compute_sim_scores,
    match_participants,
    parse_event_csv,
    parse_event_id_from_filename,
    split_event_and_result_blocks,
)

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "discord-bot" / "tests" / "fixtures"
FIXTURE_PATH = FIXTURE_DIR / "eventresult_87601875_0.csv"

# A real Hosted-session export (this league's actual race format) — no
# official-series season/week/strength-of-field metadata, and a
# "League Name"/"League ID" info block sandwiched before the real
# results table. See split_event_and_result_blocks/_parse_event_block's
# docstrings.
HOSTED_FIXTURE_PATH = FIXTURE_DIR / "eventresult_88113080_0.csv"


def _fixture_text() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8-sig")


def _hosted_fixture_text() -> str:
    return HOSTED_FIXTURE_PATH.read_text(encoding="utf-8-sig")


def test_parse_event_id_from_filename_extracts_id():
    assert parse_event_id_from_filename("eventresult_87601875_0.csv") == 87601875


def test_parse_event_id_from_filename_rejects_non_matching_name():
    with pytest.raises(InvalidFilenameError):
        parse_event_id_from_filename("results.csv")


def test_parse_event_csv_against_real_fixture_event_block():
    parsed = parse_event_csv(_fixture_text())
    assert parsed["event"] == {
        "track": "Tsukuba Circuit - 2000 Full",
        "series": "FIA Formula 4 Challenge - Fixed",
        "start_time": "2026-07-31T03:00:00Z",
        "iracing_season_year": 2026,
        "iracing_season_quarter": 3,
        "race_week": 7,
        "strength_of_field": 1922,
        "special_event_type": None,
    }
    assert len(parsed["results"]) == 22


def test_parse_event_csv_maps_full_result_row():
    parsed = parse_event_csv(_fixture_text())
    winner = parsed["results"][0]
    assert winner == {
        "finish_position": 1,
        "iracing_cust_id": 1399115,
        "iracing_display_name": "Petr Kartashov",
        "start_position": 4,
        "car_name": "FIA F4",
        "car_class": "FIA F4",
        "car_number": "1",
        "status": "Running",
        "interval": "-00.000",
        "laps_led": 16,
        "laps_completed": 17,
        "incidents": 1,
        "qualify_time": None,
        "average_lap_time": "54.686",
        "fastest_lap_time": "54.039",
        "fastest_lap_number": 6,
        "iracing_points": 119,
        "iracing_club_points": None,
        "old_irating": 3010,
        "new_irating": 3070,
        "is_ai": False,
    }


def test_parse_event_csv_handles_blanks_vs_explicit_zero():
    parsed = parse_event_csv(_fixture_text())
    last = parsed["results"][-1]  # Lucca Dalledone — Disconnected, DNF early
    assert last["laps_led"] == 0
    assert last["laps_completed"] == 0
    assert last["iracing_points"] == 0
    assert last["iracing_club_points"] is None
    assert last["fastest_lap_time"] is None
    assert last["fastest_lap_number"] is None
    assert last["qualify_time"] is None
    assert last["average_lap_time"] == "00.000"  # raw sentinel string, not parsed


def test_parse_event_csv_rejects_missing_blank_line_separator():
    with pytest.raises(CsvParseError):
        parse_event_csv('"Fin Pos","Cust ID"\n"1","123"\n')


def test_parse_event_csv_against_real_hosted_session_event_block():
    parsed = parse_event_csv(_hosted_fixture_text())
    assert parsed["event"] == {
        "track": "Circuit Zandvoort - Grand Prix",
        "series": "Hosted iRacing",
        "start_time": "2026-08-21T00:30:40Z",
        # Hosted sessions carry none of the official-series metadata.
        "iracing_season_year": None,
        "iracing_season_quarter": None,
        "race_week": None,
        "strength_of_field": None,
        "special_event_type": None,
    }
    assert len(parsed["results"]) == 10


def test_parse_event_csv_hosted_session_result_row_has_no_iracing_points_or_irating():
    parsed = parse_event_csv(_hosted_fixture_text())
    winner = parsed["results"][0]
    assert winner["finish_position"] == 1
    assert winner["iracing_display_name"] == "Mac Matott"
    assert winner["iracing_points"] is None
    assert winner["iracing_club_points"] is None
    assert winner["old_irating"] is None
    assert winner["new_irating"] is None


def test_split_skips_the_league_info_block_in_a_hosted_session_export():
    _, results_text = split_event_and_result_blocks(_hosted_fixture_text())
    assert results_text.startswith('"Fin Pos"')
    assert "League Name" not in results_text


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
