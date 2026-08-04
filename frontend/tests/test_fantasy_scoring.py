import pytest

from app.services.fantasy_scoring import (
    MultipleActiveScoringRuleVersionsError,
    ScoringRulesNotSeededError,
    _points_table_from_rule_rows,
    build_scoring_rule_rows,
    compute_driver_season_points,
    compute_round_scores,
    nascar_points_table,
    points_for_position,
)


def test_first_place_is_forty_points():
    assert nascar_points_table()[1] == 40.0


def test_points_decrease_by_one_from_second_place():
    table = nascar_points_table()
    assert table[2] == 35.0
    assert table[3] == 34.0
    assert table[22] == 15.0


def test_table_size_matches_grid_size():
    table = nascar_points_table(grid_size=3)
    assert table == {1: 40.0, 2: 35.0, 3: 34.0}


def test_build_scoring_rule_rows_shape():
    rows = build_scoring_rule_rows("season-1", grid_size=3)
    assert rows == [
        {
            "season_id": "season-1",
            "rule_type": "fantasy_f1",
            "version": "nascar-2024",
            "position": 1,
            "points": 40.0,
            "is_active": True,
        },
        {
            "season_id": "season-1",
            "rule_type": "fantasy_f1",
            "version": "nascar-2024",
            "position": 2,
            "points": 35.0,
            "is_active": True,
        },
        {
            "season_id": "season-1",
            "rule_type": "fantasy_f1",
            "version": "nascar-2024",
            "position": 3,
            "points": 34.0,
            "is_active": True,
        },
    ]


def test_points_for_position_returns_zero_for_no_result():
    table = nascar_points_table(grid_size=3)
    assert points_for_position(None, table) == 0.0


def test_points_for_position_returns_zero_for_out_of_range():
    table = nascar_points_table(grid_size=3)
    assert points_for_position(99, table) == 0.0


DRAFT_PICKS = [
    {"participant_id": "p1", "f1_driver_id": "d1"},
    {"participant_id": "p1", "f1_driver_id": "d2"},
    {"participant_id": "p2", "f1_driver_id": "d3"},
]


def test_compute_round_scores_sums_across_participants_drivers():
    table = nascar_points_table(grid_size=3)
    round_results = [
        {"f1_driver_id": "d1", "finish_position": 1, "is_sprint": False},
        {"f1_driver_id": "d2", "finish_position": 3, "is_sprint": False},
        {"f1_driver_id": "d3", "finish_position": 2, "is_sprint": False},
    ]

    scores = compute_round_scores(DRAFT_PICKS, round_results, table)

    assert scores == {"p1": 40.0 + 34.0, "p2": 35.0}


def test_compute_round_scores_combines_race_and_sprint_with_same_table():
    table = nascar_points_table(grid_size=3)
    round_results = [
        {"f1_driver_id": "d1", "finish_position": 1, "is_sprint": False},
        {"f1_driver_id": "d1", "finish_position": 2, "is_sprint": True},
        {"f1_driver_id": "d2", "finish_position": 3, "is_sprint": False},
        {"f1_driver_id": "d3", "finish_position": 2, "is_sprint": False},
    ]

    scores = compute_round_scores(DRAFT_PICKS, round_results, table)

    assert scores["p1"] == 40.0 + 35.0 + 34.0


def test_dnf_still_scored_by_classified_position():
    table = nascar_points_table(grid_size=22)
    round_results = [{"f1_driver_id": "d1", "finish_position": 15, "status": "Retired"}]

    scores = compute_round_scores(
        [{"participant_id": "p1", "f1_driver_id": "d1"}], round_results, table
    )

    assert scores["p1"] == table[15]


def test_driver_with_no_result_contributes_zero():
    table = nascar_points_table(grid_size=3)

    scores = compute_round_scores(DRAFT_PICKS, [], table)

    assert scores == {"p1": 0.0, "p2": 0.0}


def test_participant_with_zero_picks_is_absent_from_scores():
    table = nascar_points_table(grid_size=3)
    round_results = [{"f1_driver_id": "d1", "finish_position": 1}]

    scores = compute_round_scores([], round_results, table)

    assert scores == {}


def test_compute_driver_season_points_sums_across_all_rounds_and_sprints():
    table = nascar_points_table(grid_size=3)
    season_results = [
        {"f1_driver_id": "d1", "finish_position": 1, "is_sprint": False},  # round 1
        {"f1_driver_id": "d1", "finish_position": 2, "is_sprint": False},  # round 2
        {"f1_driver_id": "d1", "finish_position": 3, "is_sprint": True},   # round 2 sprint
        {"f1_driver_id": "d2", "finish_position": 1, "is_sprint": False},
    ]

    totals = compute_driver_season_points(season_results, table)

    assert totals == {"d1": 40.0 + 35.0 + 34.0, "d2": 40.0}


def test_points_table_from_rule_rows_builds_table_and_version():
    rows = [
        {"position": 1, "points": 40, "version": "nascar-2024"},
        {"position": 2, "points": 35, "version": "nascar-2024"},
    ]

    table, version = _points_table_from_rule_rows(rows)

    assert table == {1: 40.0, 2: 35.0}
    assert version == "nascar-2024"


def test_points_table_from_rule_rows_raises_on_no_rows():
    with pytest.raises(ScoringRulesNotSeededError):
        _points_table_from_rule_rows([])


def test_points_table_from_rule_rows_raises_on_mixed_versions():
    rows = [
        {"position": 1, "points": 40, "version": "nascar-2024"},
        {"position": 1, "points": 50, "version": "nascar-2025"},
    ]
    with pytest.raises(MultipleActiveScoringRuleVersionsError):
        _points_table_from_rule_rows(rows)
