from app.services.discord_webhooks import (
    compute_constructor_round_details,
    compute_fantasy_round_details,
    compute_standings_deltas,
    format_breakdown_message,
    format_message,
    format_points_lines,
    format_standings_lines,
)


def _row(pid, name, points):
    return {"participant_id": pid, "display_name": name, "points": points}


def test_compute_standings_deltas_tracks_points_gained():
    before = [_row("a", "Alice", 100), _row("b", "Bob", 90)]
    after = [_row("a", "Alice", 120), _row("b", "Bob", 90)]

    deltas = compute_standings_deltas(before, after)

    assert deltas[0]["points_gained"] == 20
    assert deltas[1]["points_gained"] == 0


def test_compute_standings_deltas_tracks_rank_movement():
    before = [_row("a", "Alice", 100), _row("b", "Bob", 90)]
    after = [_row("b", "Bob", 110), _row("a", "Alice", 100)]

    deltas = compute_standings_deltas(before, after)

    # Bob moved from rank 2 to rank 1: +1.
    assert deltas[0]["display_name"] == "Bob"
    assert deltas[0]["rank_change"] == 1
    # Alice moved from rank 1 to rank 2: -1.
    assert deltas[1]["display_name"] == "Alice"
    assert deltas[1]["rank_change"] == -1


def test_compute_standings_deltas_new_entrant_has_no_rank_change():
    before = [_row("a", "Alice", 100)]
    after = [_row("a", "Alice", 100), _row("c", "Carol", 5)]

    deltas = compute_standings_deltas(before, after)

    carol = next(d for d in deltas if d["display_name"] == "Carol")
    assert carol["rank_change"] is None
    assert carol["points_gained"] == 5


def test_compute_standings_deltas_supports_a_custom_key_field():
    before = [{"id": "team-1", "display_name": "Ferrari", "points": 10}]
    after = [{"id": "team-1", "display_name": "Ferrari", "points": 25}]

    deltas = compute_standings_deltas(before, after, key_field="id")

    assert deltas[0]["points_gained"] == 15


def test_format_points_lines_skips_zero_gain_and_sorts_descending():
    deltas = [
        {"display_name": "Alice", "points_gained": 5, "rank": 1, "rank_change": None, "points": 100},
        {"display_name": "Bob", "points_gained": 0, "rank": 2, "rank_change": None, "points": 90},
        {"display_name": "Carol", "points_gained": 20, "rank": 3, "rank_change": None, "points": 80},
    ]

    lines = format_points_lines(deltas)

    assert lines == ["Carol — +20 pts", "Alice — +5 pts"]


def test_format_standings_lines_shows_arrows_for_movement():
    deltas = [
        {"display_name": "Alice", "rank": 1, "rank_change": 1, "points": 120, "points_gained": 20},
        {"display_name": "Bob", "rank": 2, "rank_change": -1, "points": 90, "points_gained": 0},
        {"display_name": "Carol", "rank": 3, "rank_change": None, "points": 5, "points_gained": 5},
    ]

    lines = format_standings_lines(deltas)

    assert lines[0] == "1. Alice — 120 pts ▲1"
    assert lines[1] == "2. Bob — 90 pts ▼1"
    assert lines[2] == "3. Carol — 5 pts"


def test_format_message_includes_podium_points_and_standings():
    deltas = [{"display_name": "Alice", "rank": 1, "rank_change": None, "points": 20, "points_gained": 20}]

    message = format_message("🏆", "Fantasy Championship", "Round 1: Test GP", ["Max", "Lando", "Charles"], deltas)

    assert "🏆 **Fantasy Championship — Round 1: Test GP**" in message
    assert "🥇 Max  🥈 Lando  🥉 Charles" in message
    assert "**Points this round**" in message
    assert "Alice — +20 pts" in message
    assert "**Standings**" in message
    assert "1. Alice — 20 pts" in message


def test_format_message_omits_empty_sections():
    message = format_message("🌟", "Overall Championship", "Round 1", [], [])

    assert "**Points this round**" not in message
    assert "**Standings**" not in message


def _driver(full_name, points_by_round, positions_by_round):
    return {
        "full_name": full_name,
        "points_by_round": points_by_round,
        "positions_by_round": positions_by_round,
    }


def test_compute_fantasy_round_details_breaks_down_by_driver():
    breakdown = {
        "p1": [
            _driver("Driver A", {1: 20.0}, {1: [2]}),
            _driver("Driver B", {1: 14.0}, {1: [8]}),
        ],
    }
    names = {"p1": "Codey Whiteside"}

    details = compute_fantasy_round_details(breakdown, 1, names)

    assert details == [
        {
            "display_name": "Codey Whiteside",
            "driver_lines": ["Driver A (P2) — 20 pts", "Driver B (P8) — 14 pts"],
            "total": 34.0,
        }
    ]


def test_compute_fantasy_round_details_shows_both_positions_on_a_sprint_weekend():
    breakdown = {"p1": [_driver("Driver A", {2: 28.0}, {2: [2, 1]})]}
    names = {"p1": "Alice"}

    details = compute_fantasy_round_details(breakdown, 2, names)

    assert details[0]["driver_lines"] == ["Driver A (P2/P1) — 28 pts"]


def test_compute_fantasy_round_details_omits_drivers_with_no_result_that_round():
    breakdown = {
        "p1": [
            _driver("Driver A", {1: 20.0, 2: 0}, {1: [2], 2: []}),
        ],
    }
    names = {"p1": "Alice"}

    # Round 2: Driver A didn't race (positions empty) — the participant
    # shouldn't show up at all, not with a driver line showing 0 pts.
    details = compute_fantasy_round_details(breakdown, 2, names)

    assert details == []


def test_compute_fantasy_round_details_sorts_by_total_descending():
    breakdown = {
        "p1": [_driver("Driver A", {1: 5.0}, {1: [10]})],
        "p2": [_driver("Driver B", {1: 20.0}, {1: [1]})],
    }
    names = {"p1": "Low Scorer", "p2": "High Scorer"}

    details = compute_fantasy_round_details(breakdown, 1, names)

    assert [d["display_name"] for d in details] == ["High Scorer", "Low Scorer"]


def test_format_breakdown_message_shows_member_lines_indented():
    round_details = [
        {"display_name": "Codey Whiteside", "driver_lines": ["Driver A (P2) — 20 pts"], "total": 20.0}
    ]

    message = format_breakdown_message(
        "🏆", "Fantasy Championship", "Round 1: Test GP", ["Max"], round_details, []
    )

    assert "🏆 **Fantasy Championship — Round 1: Test GP**" in message
    assert "**Codey Whiteside** — +20 pts" in message
    assert "↳ Driver A (P2) — 20 pts" in message


def test_format_breakdown_message_supports_no_podium():
    round_details = [
        {"display_name": "Ferrari", "driver_lines": ["Alice (P1) — 12 pts"], "total": 12.0}
    ]

    message = format_breakdown_message(
        "👥", "Constructors' Championship", "Round 11: Hungarian GP", [], round_details, []
    )

    assert "👥 **Constructors' Championship — Round 11: Hungarian GP**" in message
    assert "🥇" not in message
    assert "**Ferrari** — +12 pts" in message
    assert "↳ Alice (P1) — 12 pts" in message


def _pair(name, members):
    return {
        "name": name,
        "member_names": " & ".join(m[1] for m in members),
        "constructor_members": [{"participant_id": pid} for pid, _ in members],
    }


def test_compute_constructor_round_details_groups_points_by_team():
    pairs = [
        {
            "name": "Ferrari",
            "member_names": "Alice & Bob",
            "constructor_members": [
                {"participant_id": "a", "participants": {"display_name": "Alice"}},
                {"participant_id": "b", "participants": {"display_name": "Bob"}},
            ],
        }
    ]
    points_by_participant = {"a": 12.0, "b": 8.0}
    position_by_participant = {"a": 1, "b": 5}

    details = compute_constructor_round_details(pairs, points_by_participant, position_by_participant)

    assert details == [
        {
            "display_name": "Ferrari",
            "driver_lines": ["Alice (P1) — 12 pts", "Bob (P5) — 8 pts"],
            "total": 20.0,
        }
    ]


def test_compute_constructor_round_details_omits_members_with_no_result():
    pairs = [
        {
            "name": "McLaren",
            "member_names": "Carol & Dan",
            "constructor_members": [
                {"participant_id": "c", "participants": {"display_name": "Carol"}},
                {"participant_id": "d", "participants": {"display_name": "Dan"}},
            ],
        }
    ]
    # Only Carol raced this event.
    details = compute_constructor_round_details(pairs, {"c": 10.0}, {"c": 3})

    assert details == [
        {"display_name": "McLaren", "driver_lines": ["Carol (P3) — 10 pts"], "total": 10.0}
    ]


def test_compute_constructor_round_details_marks_the_lowest_of_three_as_dropped():
    pairs = [
        {
            "name": "Red Bull",
            "member_names": "Mac & Caleb & Dylan",
            "constructor_members": [
                {"participant_id": "m", "participants": {"display_name": "Mac"}},
                {"participant_id": "c", "participants": {"display_name": "Caleb"}},
                {"participant_id": "d", "participants": {"display_name": "Dylan"}},
            ],
        }
    ]
    points_by_participant = {"m": 11.0, "c": 4.0, "d": 1.0}
    position_by_participant = {"m": 1, "c": 4, "d": 8}

    details = compute_constructor_round_details(pairs, points_by_participant, position_by_participant)

    assert details == [
        {
            "display_name": "Red Bull",
            "driver_lines": ["Mac (P1) — 11 pts", "Caleb (P4) — 4 pts", "Dylan (P8) — 1 pts (dropped)"],
            "total": 15.0,
        }
    ]


def test_compute_constructor_round_details_omits_teams_with_no_results_at_all():
    pairs = [
        {
            "name": "Williams",
            "member_names": "Eve & Frank",
            "constructor_members": [
                {"participant_id": "e", "participants": {"display_name": "Eve"}},
                {"participant_id": "f", "participants": {"display_name": "Frank"}},
            ],
        }
    ]
    details = compute_constructor_round_details(pairs, {}, {})

    assert details == []
