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
    assert rows[0] == {"display_name": "Unknown", "role": "member", "points": 5}


def _pair(name, member_ids, member_names="A & B"):
    return {
        "name": name,
        "member_names": member_names,
        "logo_url": None,
        "constructor_members": [{"participant_id": pid} for pid in member_ids],
    }


def test_pair_points_sums_both_members_sim_totals():
    assert _pair_points(_pair(None, ["a", "b"]), {"a": 10, "b": 5}) == 15


def test_pair_points_treats_unscored_member_as_zero():
    assert _pair_points(_pair(None, ["a", "c"]), {"a": 10}) == 10
