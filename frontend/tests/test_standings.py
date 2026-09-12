from app.services.standings import (
    HALF_SEASON_BEST_N,
    _attach_round_metrics,
    _best_n_total,
    _entry_before_total,
    _entry_cumulative_at,
    _rows_from_totals,
    _sum_points,
    constructor_round_points,
    get_points_progression,
    round_half_up,
)

PARTICIPANTS = {
    "a": {"display_name": "Alice", "role": "owner", "car_number": 7},
    "b": {"display_name": "Bob", "role": "member", "car_number": None},
}


def test_sum_points_totals_across_sources():
    totals = _sum_points([
        [{"participant_id": "a", "points": 10}],
        [{"participant_id": "a", "points": 5}, {"participant_id": "b", "points": 3}],
    ])
    assert totals == {"a": 15, "b": 3}


def test_rows_from_totals_sorts_descending_and_rounds():
    rows = _rows_from_totals({"a": 10.05, "b": 12.333}, PARTICIPANTS)
    assert [r["display_name"] for r in rows] == ["Bob", "Alice"]
    assert rows[0]["points"] == 12.3


def test_rows_from_totals_carries_car_number_through():
    rows = _rows_from_totals({"a": 10, "b": 5}, PARTICIPANTS)
    by_name = {r["display_name"]: r["car_number"] for r in rows}
    assert by_name == {"Alice": 7, "Bob": None}


def test_rows_from_totals_unknown_participant_falls_back():
    rows = _rows_from_totals({"ghost": 5}, PARTICIPANTS)
    assert rows[0] == {
        "participant_id": "ghost",
        "display_name": "Unknown",
        "role": "member",
        "car_number": None,
        "points": 5,
    }


def test_best_n_total_counts_everything_when_fewer_than_best_n_raced():
    # Only 3 raced rounds, well under HALF_SEASON_BEST_N (9) — nothing to
    # drop, they all count.
    points_by_round = {12: 10, 13: 20, 14: 5}
    total, dropped = _best_n_total(points_by_round, {12, 13, 14})
    assert total == 35
    assert dropped == set()


def test_best_n_total_drops_the_worst_beyond_best_n():
    # 10 raced rounds (12-21) — one worse than HALF_SEASON_BEST_N (9), so
    # exactly the single worst-scoring one (round 15, 1 point) is dropped.
    points_by_round = {r: 10 for r in range(12, 22)}
    points_by_round[15] = 1
    raced = set(range(12, 22))
    total, dropped = _best_n_total(points_by_round, raced)
    assert dropped == {15}
    assert total == sum(points_by_round[r] for r in raced if r != 15) == 90


def test_best_n_total_ignores_rounds_outside_the_half_season_window():
    # Round 24 is outside HALF_SEASON_SIM_ROUNDS (12-23) — never counts,
    # and never shows up as "dropped" either, since it was never a
    # candidate in the first place.
    points_by_round = {12: 10, 24: 999}
    total, dropped = _best_n_total(points_by_round, {12, 24})
    assert total == 10
    assert dropped == set()


def test_best_n_total_exclude_round_can_reinstate_a_previously_dropped_round():
    # 10 raced rounds with round 15 the worst (dropped from the full
    # total). Excluding the newest round (21) to reconstruct "the total
    # as of last round" means only 9 candidates remain, so round 15 is
    # no longer anyone's 10th-best — it's back in.
    points_by_round = {r: 10 for r in range(12, 22)}
    points_by_round[15] = 1
    raced = set(range(12, 22))
    before_total, before_dropped = _best_n_total(points_by_round, raced, exclude_round=21)
    assert before_dropped == set()
    assert before_total == sum(points_by_round[r] for r in raced if r != 21) == 81


def test_entry_before_total_uses_precomputed_value_when_present():
    driver = {"before_total": 42, "total": 50, "points_by_round": {12: 8}}
    assert _entry_before_total(driver, latest_round=12) == 42


def test_entry_before_total_falls_back_to_subtraction_without_one():
    driver = {"total": 50, "points_by_round": {12: 8}}
    assert _entry_before_total(driver, latest_round=12) == 42


def test_entry_before_total_returns_total_when_no_latest_round():
    driver = {"total": 50, "points_by_round": {}}
    assert _entry_before_total(driver, latest_round=None) == 50


def test_half_season_best_n_is_nine():
    assert HALF_SEASON_BEST_N == 9


def test_entry_cumulative_at_replays_best_n_for_a_sim_entry():
    # 10 raced rounds, round 15 the worst (1 pt) — through round 20 (only
    # 9 raced rounds so far, including the 1-pt one), nothing's dropped
    # yet; once round 21 (the 10th raced round) is included, the 1-pt
    # round becomes the worst and gets dropped.
    points_by_round = {r: 10 for r in range(12, 22)}
    points_by_round[15] = 1
    positions_by_round = {r: [5] for r in range(12, 22)}
    driver = {
        "points_by_round": points_by_round,
        "positions_by_round": positions_by_round,
        "before_total": 0,  # presence of this key marks it sim-derived
    }
    assert _entry_cumulative_at(driver, upto_round=20) == 81  # 8 rounds of 10 + the 1-pt round
    assert _entry_cumulative_at(driver, upto_round=21) == 90  # 9 rounds of 10, 1-pt round dropped


def test_entry_cumulative_at_is_a_plain_running_sum_without_before_total():
    driver = {"points_by_round": {12: 5, 13: 7, 14: 100}}
    assert _entry_cumulative_at(driver, upto_round=13) == 12


def test_get_points_progression_matches_final_row_points():
    rows = [
        {
            "display_name": "Alice",
            "car_number": 7,
            "participant_id": "a",
            "driver_breakdown": [{"points_by_round": {12: 5, 13: 7}}],
        }
    ]
    progression = get_points_progression(rows, [12, 13])
    assert progression == [
        {"label": "Alice", "car_number": 7, "participant_id": "a", "points": [5, 12]}
    ]


def test_round_half_up_rounds_ties_up_not_to_even():
    assert round_half_up(13.5) == 14
    assert round_half_up(6.5) == 7  # Python's round(6.5) would give 6 (round-to-even)
    assert round_half_up(6.4) == 6
    assert round_half_up(6.6) == 7


def test_constructor_round_points_two_scorers_is_a_plain_sum():
    assert constructor_round_points([10, 5]) == 15


def test_constructor_round_points_three_scorers_keeps_top_and_averages_the_rest():
    # Top scorer (20) counts in full; the other two (15, 5) are averaged
    # (10) and rounded — nobody's result is fully discarded.
    assert constructor_round_points([20, 15, 5]) == 30


def test_constructor_round_points_rounds_a_tied_average_up():
    # avg(15, 12) = 13.5 -> rounds up to 14, not down to 13 or to-even.
    assert constructor_round_points([22, 15, 12]) == 22 + 14


def test_constructor_round_points_blends_final_half_season_totals_for_three_person_team():
    # get_constructor_standings now calls this once on each member's own
    # half-season best-9-of-12 total (see HALF_SEASON_SIM_ROUNDS), not
    # per individual round — same formula, applied one level up: the
    # top total counts in full, the other two are averaged together.
    member_totals = [120, 90, 60]
    assert constructor_round_points(member_totals) == 120 + round_half_up((90 + 60) / 2)


def test_constructor_round_points_two_person_team_is_a_plain_sum_of_totals():
    assert constructor_round_points([120, 90]) == 210


def _sim_driver(before_total, total, latest_positions):
    """A minimal driver_breakdown entry for _attach_round_metrics tests —
    only the fields it actually reads (before_total/total for the blend,
    positions_by_round to tell a no-show from a real result)."""
    return {
        "before_total": before_total,
        "total": total,
        "positions_by_round": {14: latest_positions},
    }


def test_attach_round_metrics_constructor_round_credit_excludes_a_no_show_member():
    # Mirrors a real scenario: a 3-person team's third member has no
    # result at all for the latest round (not just a bad one) — their
    # before_total and total are identical (32, 32) since a round they
    # didn't race can't move their own best-9 total either way.
    row = {
        "id": "red-bull",
        "points": 101.0,
        "driver_breakdown": [
            _sim_driver(44, 64, [2]),  # raced, P2
            _sim_driver(26, 41, [7]),  # raced, P7
            _sim_driver(32, 32, []),  # no-show
        ],
    }

    _attach_round_metrics([row], [13, 14], key_field="id")

    # Full credit for both members who actually raced (20 + 15), not the
    # no-show's unchanged total dragging the "averaged" half down to 8.
    assert row["this_round_points"] == 35.0


def test_attach_round_metrics_constructor_round_credit_still_blends_when_everyone_raced():
    # No no-show this time — every member has a real latest-round result,
    # so the fair-credit recompute should land on the same blended
    # number the plain points-minus-before_total formula already gives.
    row = {
        "id": "red-bull",
        "points": 105.0,
        "driver_breakdown": [
            _sim_driver(44, 64, [2]),
            _sim_driver(26, 41, [7]),
            _sim_driver(32, 40, [9]),  # raced this time, gained 8
        ],
    }

    _attach_round_metrics([row], [13, 14], key_field="id")

    assert row["this_round_points"] == 32.0


def test_attach_round_metrics_rank_change_still_reflects_the_full_roster():
    # The no-show fix only touches this_round_points — rank_change and
    # gap_to_leader should still be based on the true prior standings
    # (the no-show's total included), not the filtered round-credit view.
    # Rows come in already sorted by points descending, same as every
    # real caller (get_constructor_standings sorts before this runs).
    full_roster_team = {
        "id": "racing-bulls",
        "points": 104.0,
        "driver_breakdown": [
            _sim_driver(40, 60, [1]),
            _sim_driver(28, 44, [5]),
        ],
    }
    no_show_team = {
        "id": "red-bull",
        "points": 101.0,
        "driver_breakdown": [
            _sim_driver(44, 64, [2]),
            _sim_driver(26, 41, [7]),
            _sim_driver(32, 32, []),
        ],
    }

    _attach_round_metrics([full_roster_team, no_show_team], [13, 14], key_field="id")

    # True before-totals: red-bull 44+round_half_up((26+32)/2)=73, racing-bulls
    # 40+28=68 — red-bull was already ahead before this round (not the
    # filtered 70 the round-credit calc uses internally), so it's racing-bulls
    # that moved up a spot and red-bull that slipped, even though red-bull's
    # this_round_points (35, from the test above) beats racing-bulls' gain.
    assert no_show_team["rank_change"] == -1
    assert full_roster_team["rank_change"] == 1
    assert no_show_team["gap_to_leader"] == 3.0
