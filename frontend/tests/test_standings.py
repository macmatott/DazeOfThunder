from app.services.standings import _pair_points, _rows_from_totals, _sum_points

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


def test_pair_points_drops_the_lowest_of_three_each_round():
    # This league's one 3-person team — dropping the lowest scorer each
    # round keeps them from getting an extra scoring opportunity that
    # 2-person teams don't get.
    points_by_round = {
        "r1": {"a": 20, "b": 15, "c": 5},   # c dropped this round
        "r2": {"a": 3, "b": 25, "c": 10},   # a dropped this round
    }
    assert _pair_points(_pair(None, ["a", "b", "c"]), points_by_round) == (20 + 15) + (25 + 10)


def test_pair_points_three_person_team_matches_two_person_math_when_one_is_absent():
    # A round where the 3rd member didn't score at all (0) should behave
    # exactly like a 2-person team's round.
    points_by_round = {"r1": {"a": 12, "b": 7}}
    assert _pair_points(_pair(None, ["a", "b", "c"]), points_by_round) == 19
