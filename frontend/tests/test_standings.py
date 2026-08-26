from app.services.standings import (
    _pair_points,
    _rows_from_totals,
    _sum_points,
    constructor_round_points,
    round_half_up,
)

PARTICIPANTS = {
    "a": {"display_name": "Alice", "role": "owner"},
    "b": {"display_name": "Bob", "role": "member"},
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


def test_rows_from_totals_unknown_participant_falls_back():
    rows = _rows_from_totals({"ghost": 5}, PARTICIPANTS)
    assert rows[0] == {
        "participant_id": "ghost",
        "display_name": "Unknown",
        "role": "member",
        "points": 5,
    }


def _pair(name, member_ids, member_names="A & B"):
    return {
        "name": name,
        "member_names": member_names,
        "logo_url": None,
        "constructor_members": [{"participant_id": pid} for pid in member_ids],
    }


def test_pair_points_sums_both_members_across_rounds():
    points_by_round = {
        "r1": {"a": 10, "b": 5},
        "r2": {"a": 8, "b": 4},
    }
    assert _pair_points(_pair(None, ["a", "b"]), points_by_round) == 27


def test_pair_points_treats_unscored_member_as_zero():
    points_by_round = {"r1": {"a": 10}}
    assert _pair_points(_pair(None, ["a", "c"]), points_by_round) == 10


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


def test_pair_points_averages_the_bottom_two_of_three_each_round():
    # This league's one 3-person team — averaging the other two scorers
    # each round (rather than dropping the lowest outright) means a weak
    # night from either of them still pulls the round down somewhat.
    points_by_round = {
        "r1": {"a": 20, "b": 15, "c": 5},   # 20 + round(avg(15, 5)) = 20 + 10 = 30
        "r2": {"a": 3, "b": 25, "c": 10},   # 25 + round(avg(10, 3)) = 25 + 7 = 32
    }
    assert _pair_points(_pair(None, ["a", "b", "c"]), points_by_round) == 30 + 32


def test_pair_points_three_person_team_still_averages_in_an_absent_member():
    # Unlike the old "drop the lowest" rule, a 3rd member scoring 0 (e.g.
    # didn't race) still gets folded into the average, dragging the
    # round down below what a 2-person team would've scored: 12 +
    # round(avg(7, 0)) = 12 + round(3.5) = 12 + 4 = 16, not 12 + 7 = 19.
    points_by_round = {"r1": {"a": 12, "b": 7}}
    assert _pair_points(_pair(None, ["a", "b", "c"]), points_by_round) == 16
