"""
Formula Fantasy standings — 4 championships, all derived from
sim_points_awarded/fantasy_points_awarded rather than a materialized
view (see /docs/architecture.md on avoiding premature optimization
here). Reads go through admin_client(): participants/sim_points_awarded/
fantasy_points_awarded have RLS enabled with no read policies (only
seasons/f1_drivers/f1_race_results are publicly readable), so
public_client() would silently return empty results here regardless of
data — same reasoning every other service module already uses
admin_client() for.

NOTE: Overall/Constructors' Championship weighting (direct addition vs.
normalized/percentage-based) is still an open question — this currently
does direct addition as a placeholder.

HALF-SEASON BEST-9-OF-12 (league decision, in effect for the current
half-season only — see HALF_SEASON_SIM_ROUNDS below): every Sim Racing
total on the site — Drivers', Constructors', and the Sim half of
Overall — counts only each participant's best HALF_SEASON_BEST_N
results within that round window, live-recomputed every week rather
than settled once at the end. Fantasy F1 scoring is untouched by this;
scheduling conflicts are a Sim Racing (attendance) problem, not a
Fantasy (drafted real-world driver) one.
"""

import math
from collections import defaultdict

from app.db.supabase_client import admin_client
from app.services.constructor_draft import get_pairs

STANDINGS_TABS = {"overall", "fantasy", "sim", "constructors"}

TAB_LABELS = {
    "overall": "Overall Championship",
    "fantasy": "Fantasy Championship",
    "sim": "Drivers' Championship",
    "constructors": "Constructors' Championship",
}

TAB_EMPTY_COPY = {
    "overall": "No points scored yet — check back once the season gets underway.",
    "fantasy": "No Fantasy F1 points scored yet — check back once real races start.",
    "sim": "No Sim Racing points scored yet — check back once iRacing events start.",
    "constructors": "Teams haven't been paired yet — check back once the Constructor draft happens.",
}

# The 12 sim rounds making up this currently-running half-season. Round
# 12 was this league's actual first sim race (the league started mid-
# season on the F1 calendar — rounds 1-11 were never raced), running
# through round 23. League decision: each participant's half-season Sim
# Racing total counts only their best HALF_SEASON_BEST_N results within
# this window, so a scheduling conflict costs at most HALF_SEASON_SIM_
# ROUNDS minus BEST_N races (currently 3) before it stops affecting
# their total at all. Not yet defined: what rule (if any) applies to a
# second half beyond round 23 — revisit this window once that's decided.
HALF_SEASON_SIM_ROUNDS = range(12, 24)
HALF_SEASON_BEST_N = 9


def _best_n_total(
    points_by_round: dict[int, float], raced_rounds: set[int], *, exclude_round: int | None = None
) -> tuple[float, set[int]]:
    """The sum of the best HALF_SEASON_BEST_N of raced_rounds that fall
    within HALF_SEASON_SIM_ROUNDS (excluding exclude_round if given —
    used to reconstruct "the total as of last round" for this-round-
    gained/rank-change, since a newly-raced round can knock a
    previously-counted one out of the top N rather than simply adding
    on top of the old total). A round outside the half-season window
    never counts at all, not even as one of the "dropped" ones. Fewer
    than HALF_SEASON_BEST_N raced rounds just all count in full — the
    drop only ever removes the worst of whatever's beyond that.

    Returns (total, dropped_rounds) — dropped_rounds is every raced,
    in-window round (other than exclude_round) that didn't make the
    cut, purely for display (e.g. struck through in the breakdown table
    so it's clear why a round doesn't count)."""
    candidates = [r for r in raced_rounds if r in HALF_SEASON_SIM_ROUNDS and r != exclude_round]
    ranked = sorted(candidates, key=lambda r: points_by_round.get(r, 0), reverse=True)
    kept = set(ranked[:HALF_SEASON_BEST_N])
    dropped = set(ranked[HALF_SEASON_BEST_N:])
    total = round(sum(points_by_round.get(r, 0) for r in kept), 1)
    return total, dropped


def _get_participants(client) -> dict[str, dict]:
    participants = client.table("participants").select("id, display_name, role, car_number").execute()
    return {p["id"]: p for p in participants.data}


def _sum_points(rows_by_source: list[list[dict]]) -> dict[str, float]:
    """Sums points across however many raw point-row lists are given (each
    row has participant_id, points), one participant_id per output key."""
    totals: dict[str, float] = defaultdict(float)
    for rows in rows_by_source:
        for row in rows:
            totals[row["participant_id"]] += row["points"]
    return totals


def _rows_from_totals(totals: dict[str, float], participants: dict[str, dict]) -> list[dict]:
    unknown = {"display_name": "Unknown", "role": "member", "car_number": None}
    standings = [
        {
            "participant_id": pid,
            "display_name": participants.get(pid, unknown)["display_name"],
            "role": participants.get(pid, unknown)["role"],
            "car_number": participants.get(pid, unknown).get("car_number"),
            "points": round(points, 1),
        }
        for pid, points in totals.items()
    ]
    standings.sort(key=lambda row: row["points"], reverse=True)
    return standings


def _build_standings(rows_by_source: list[list[dict]], participants: dict[str, dict]) -> list[dict]:
    return _rows_from_totals(_sum_points(rows_by_source), participants)


def get_formula_fantasy_standings(season_id: str | None = None) -> list[dict]:
    """
    Overall Championship — half-season best-9-of-12 Sim Racing total (see
    HALF_SEASON_SIM_ROUNDS) plus full-season Fantasy F1 points combined.
    Returns [{"display_name": ..., "role": ..., "points": ...}, ...]
    sorted descending. Empty list if there's no season yet or nothing
    has been scored.
    """
    client = admin_client()
    participants = _get_participants(client)

    fantasy_query = client.table("fantasy_points_awarded").select("participant_id, points")
    if season_id:
        fantasy_query = fantasy_query.eq("season_id", season_id)

    sim_breakdown, _ = get_sim_breakdown_by_participant(season_id)
    fantasy_totals = _sum_points([fantasy_query.execute().data])

    combined: dict[str, float] = defaultdict(float)
    for pid, entry in sim_breakdown.items():
        combined[pid] += entry["total"]
    for pid, points in fantasy_totals.items():
        combined[pid] += points

    return _rows_from_totals(combined, participants)


def get_fantasy_only_standings(season_id: str | None = None) -> list[dict]:
    """Fantasy Championship — fantasy_points_awarded only, no sim racing."""
    client = admin_client()
    participants = _get_participants(client)

    fantasy_query = client.table("fantasy_points_awarded").select("participant_id, points")
    if season_id:
        fantasy_query = fantasy_query.eq("season_id", season_id)

    return _build_standings([fantasy_query.execute().data], participants)


def get_sim_only_standings(season_id: str | None = None) -> list[dict]:
    """Drivers' Championship — each participant's half-season best-9-of-12
    Sim Racing total (see HALF_SEASON_SIM_ROUNDS), not a plain full-season
    sum. Every participant gets a row here even at 0 points (unlike the
    other 3 tabs, which only show whoever's actually scored) — someone
    who hasn't raced a round yet this season should still show up on the
    roster rather than looking like they don't exist."""
    client = admin_client()
    participants = _get_participants(client)
    breakdown, _ = get_sim_breakdown_by_participant(season_id)
    totals = {pid: 0.0 for pid in participants}
    totals.update({pid: entry["total"] for pid, entry in breakdown.items()})
    return _rows_from_totals(totals, participants)


def _get_sim_results_by_round(
    client, season_id: str
) -> tuple[dict[str, dict[int, float]], dict[str, dict[int, int]], list[int]]:
    """(points_by_participant, positions_by_participant, rounds), each
    participant-keyed dict mapping ff_round_number -> that round's value.
    Shared by get_sim_breakdown_by_participant and
    get_constructor_breakdown_by_team below — both need the same raw
    per-round sim results, just grouped differently afterward."""
    events = (
        client.table("race_events")
        .select("id, ff_round_number")
        .eq("season_id", season_id)
        .eq("is_superseded", False)
        .execute()
        .data
    )
    round_by_event = {e["id"]: e["ff_round_number"] for e in events if e["ff_round_number"] is not None}
    rounds = sorted(set(round_by_event.values()))
    if not rounds:
        return {}, {}, []

    points_rows = (
        client.table("sim_points_awarded").select("participant_id, points, race_event_id").execute().data
    )
    position_rows = (
        client.table("race_results")
        .select("participant_id, finish_position, race_event_id")
        .execute()
        .data
    )

    points_by_participant: dict[str, dict[int, float]] = defaultdict(dict)
    for row in points_rows:
        rnd = round_by_event.get(row["race_event_id"])
        if rnd is not None:
            points_by_participant[row["participant_id"]][rnd] = row["points"]

    positions_by_participant: dict[str, dict[int, int]] = defaultdict(dict)
    for row in position_rows:
        participant_id = row["participant_id"]
        rnd = round_by_event.get(row["race_event_id"])
        if participant_id and rnd is not None:
            positions_by_participant[participant_id][rnd] = row["finish_position"]

    return points_by_participant, positions_by_participant, rounds


def get_sim_breakdown_by_participant(season_id: str | None) -> tuple[dict[str, dict], list[int]]:
    """Per-round sim points/finish position for every participant's own
    results — feeds the Drivers' Championship standings page's per-
    member dropdown, the same interaction as the Fantasy tab's per-
    driver breakdown table but with a single "driver" row (themselves),
    since Drivers' scores each racer on their own sim results, not a
    drafted pair.

    `total` is each participant's half-season best-9-of-12 total (see
    HALF_SEASON_SIM_ROUNDS/_best_n_total), not a plain sum of
    points_by_round — `dropped_rounds` flags which raced rounds didn't
    make their best 9, for display. `before_total` is the same best-9
    total recomputed as of the round before the latest one, so
    _attach_round_metrics can work out this round's gain/rank-change
    correctly even though a new round can knock a previously-counted
    one out of the top 9 rather than simply adding on top.

    Returns ({participant_id: {"points_by_round": {round_number:
    points}, "positions_by_round": {round_number: [finish_position]},
    "dropped_rounds", "before_total", "total"}}, rounds) — `rounds` is
    every ff_round_number with a scored (non-superseded) race_event this
    season, ascending."""
    if not season_id:
        return {}, []
    client = admin_client()
    points_by_participant, positions_by_participant, rounds = _get_sim_results_by_round(client, season_id)
    if not rounds:
        return {}, []

    latest_round = max(rounds)
    breakdown: dict[str, dict] = {}
    for participant_id in set(points_by_participant) | set(positions_by_participant):
        points_by_round = {
            rnd: points_by_participant.get(participant_id, {}).get(rnd, 0) for rnd in rounds
        }
        positions_by_round = {
            rnd: (
                [positions_by_participant[participant_id][rnd]]
                if rnd in positions_by_participant.get(participant_id, {})
                else []
            )
            for rnd in rounds
        }
        raced_rounds = {r for r, positions in positions_by_round.items() if positions}
        total, dropped_rounds = _best_n_total(points_by_round, raced_rounds)
        before_total, _ = _best_n_total(points_by_round, raced_rounds, exclude_round=latest_round)
        breakdown[participant_id] = {
            "points_by_round": points_by_round,
            "positions_by_round": positions_by_round,
            "dropped_rounds": dropped_rounds,
            "before_total": before_total,
            "total": total,
        }

    return breakdown, rounds


def get_constructor_breakdown_by_team(season_id: str | None) -> tuple[dict[str, list[dict]], list[int]]:
    """Per-round sim points/finish position for every constructor team's
    own members — feeds the Constructors' standings page's per-team
    dropdown, the same interaction as Fantasy/Drivers' but with one
    "driver" row per team member.

    Each member's own `total`/`before_total`/`dropped_rounds` are their
    individual half-season best-9-of-12 figures (see
    get_sim_breakdown_by_participant) — identical to what they'd see on
    their own Drivers' Championship row. A team's actual standings total
    (see get_constructor_standings/constructor_round_points) blends
    those totals once — top scorer's in full, the rest averaged — not a
    per-round blend anymore, so `total_is_averaged` flags a non-top
    member on this league's one 3-person team at the whole-total level
    (a 2-person team's "everyone but the top scorer" is just the other
    member, unchanged, so marking it would be noise). `rank` is each
    member's 0-indexed position sorted by total descending (0 = top
    scorer), unconditional on team size — used to pick a team's
    primary/secondary/tertiary livery color per member's bar on the
    Team Breakdown chart; ties keep pair["constructor_members"]'s own
    (alphabetical) order."""
    if not season_id:
        return {}, []
    sim_breakdown, rounds = get_sim_breakdown_by_participant(season_id)
    if not rounds:
        return {}, []

    empty_entry = {
        "points_by_round": {rnd: 0 for rnd in rounds},
        "positions_by_round": {rnd: [] for rnd in rounds},
        "dropped_rounds": set(),
        "before_total": 0,
        "total": 0,
    }

    pairs = get_pairs(season_id)
    breakdown: dict[str, list[dict]] = {}
    for pair in pairs:
        member_ids = [m["participant_id"] for m in pair["constructor_members"]]
        member_totals = {pid: sim_breakdown.get(pid, empty_entry)["total"] for pid in member_ids}
        top_pid = max(member_totals, key=member_totals.get) if member_totals else None
        ranked_ids = sorted(member_ids, key=lambda pid: member_totals[pid], reverse=True)
        rank_by_pid = {pid: i for i, pid in enumerate(ranked_ids)}

        members_breakdown = []
        for member in pair["constructor_members"]:
            pid = member["participant_id"]
            entry = sim_breakdown.get(pid, empty_entry)
            members_breakdown.append(
                {
                    **entry,
                    "full_name": member["participants"]["display_name"],
                    "car_number": member["participants"].get("car_number"),
                    "photo_url": None,
                    "logo_url": None,
                    "total_is_averaged": len(member_ids) > 2 and pid != top_pid,
                    "rank": rank_by_pid[pid],
                }
            )
        breakdown[pair["id"]] = members_breakdown

    return breakdown, rounds


def round_half_up(value: float) -> int:
    """Standard round-to-nearest, ties rounding up (unlike Python's
    built-in round(), which rounds ties to even) — e.g. 13.5 -> 14, not
    12.5's usual "round to even" surprise. Only ever applied to
    non-negative point totals here."""
    return math.floor(value + 0.5)


def constructor_round_points(scores: list[float]) -> float:
    """Blends a team's score from its members' scores: the top scorer's
    counts in full, plus the average of everyone else's, rounded to the
    nearest whole point (see round_half_up). For a 2-person team this is
    just a plain sum — averaging one remaining score with itself is that
    score. For this league's one 3-person team, it means no member's
    result is ever fully discarded the way an earlier "best 2 of 3" rule
    allowed; a weak score from either non-top scorer still pulls the
    total down somewhat, just softened by averaging rather than dropped
    outright.

    Despite the name, this isn't only used per-round anymore: standings.
    get_constructor_standings reuses it once on each member's final
    half-season best-9-of-12 total (see HALF_SEASON_SIM_ROUNDS) rather
    than per individual round — the formula's the same either way, it
    doesn't care what the numbers represent. discord_webhooks.py's
    single-race Discord recap still calls it the original, literal
    per-round way."""
    if not scores:
        return 0.0
    ranked = sorted(scores, reverse=True)
    top, rest = ranked[0], ranked[1:]
    if not rest:
        return top
    return top + round_half_up(sum(rest) / len(rest))


def get_overall_breakdown_by_participant(
    season_id: str | None,
) -> tuple[dict[str, list[dict]], list[int], set[int]]:
    """Per-round breakdown for the Overall Championship's dropdown —
    each participant's 2 drafted Fantasy drivers plus their own Sim
    Racing entry, three "driver" rows total, since Overall is just
    those two championships added together.

    Fantasy's rounds are the real F1 calendar's round numbers; Sim's
    rounds are each race_event's admin-assigned ff_round_number — the
    same numbering space by design (an iRacing race is mapped onto
    "this counts as Round 7", see race_events.ff_round_number), so the
    two round lists are unioned into one shared column set rather than
    kept separate."""
    if not season_id:
        return {}, [], set()

    from app.services.fantasy_scoring import get_fantasy_breakdown_by_participant

    fantasy_breakdown, fantasy_rounds, sprint_rounds = get_fantasy_breakdown_by_participant(season_id)
    sim_breakdown, sim_rounds = get_sim_breakdown_by_participant(season_id)
    rounds = sorted(set(fantasy_rounds) | set(sim_rounds))

    def _reindexed(entry: dict) -> dict:
        return {
            **entry,
            "points_by_round": {r: entry["points_by_round"].get(r, 0) for r in rounds},
            "positions_by_round": {r: entry["positions_by_round"].get(r, []) for r in rounds},
        }

    breakdown: dict[str, list[dict]] = {}
    for pid in set(fantasy_breakdown) | set(sim_breakdown):
        entries = [_reindexed(driver) for driver in fantasy_breakdown.get(pid, [])]
        sim_entry = sim_breakdown.get(pid)
        if sim_entry:
            entries.append(
                {
                    **_reindexed(sim_entry),
                    "full_name": "Sim Racing",
                    "photo_url": None,
                    "logo_url": None,
                    "is_sim_entry": True,
                }
            )
        breakdown[pid] = entries

    return breakdown, rounds, sprint_rounds


def get_constructor_standings(season_id: str | None) -> list[dict]:
    """Constructors' Championship — each formed pair's combined
    half-season best-9-of-12 Sim Racing total (see HALF_SEASON_SIM_ROUNDS):
    each member's own best-9 total, blended via constructor_round_points
    (top scorer's in full, the rest averaged in). One row per pair; a
    pair shows once formed even at 0 points. Empty only before the
    constructor draft has paired anyone."""
    if not season_id:
        return []
    sim_breakdown, _ = get_sim_breakdown_by_participant(season_id)
    pairs = get_pairs(season_id)

    standings = [
        {
            "id": pair["id"],
            "display_name": pair["name"] or pair["member_names"],
            "role": None,
            "points": round(
                constructor_round_points(
                    [
                        sim_breakdown.get(m["participant_id"], {}).get("total", 0)
                        for m in pair["constructor_members"]
                    ]
                ),
                1,
            ),
            "logo_url": pair["logo_url"],
            "color": pair.get("color"),
            "secondary_color": pair.get("secondary_color"),
            "tertiary_color": pair.get("tertiary_color"),
        }
        for pair in pairs
    ]
    standings.sort(key=lambda row: row["points"], reverse=True)
    return standings


def _entry_before_total(driver: dict, latest_round: int | None) -> float:
    """A driver_breakdown entry's total as of the round before
    latest_round — used by _attach_round_metrics to work out this
    round's point gain without a separate history/snapshot table.

    A sim-derived entry (a Drivers' Championship row, the Overall tab's
    "Sim Racing" sub-entry, a Constructors' team member) carries an
    explicit before_total already (see get_sim_breakdown_by_participant)
    — the half-season best-9-of-12 rule means a newly-raced round can
    knock a previously-counted one out of the top 9 rather than simply
    adding on top of the old total, so a plain subtraction would be
    wrong for those. Anything else (a drafted Fantasy F1 driver,
    unaffected by that rule) falls back to a plain subtraction."""
    if "before_total" in driver:
        return driver["before_total"]
    if latest_round is None:
        return driver["total"]
    return driver["total"] - driver["points_by_round"].get(latest_round, 0)


def _entry_cumulative_at(driver: dict, upto_round: int) -> float:
    """A driver_breakdown entry's total using only rounds up to and
    including upto_round — same idea as _entry_before_total, generalized
    to any round boundary rather than just "the round before latest".
    Feeds the points-progression chart, so a sim-derived entry replays
    the half-season best-9-of-12 rule (see _best_n_total) at each round
    rather than a naive running sum — otherwise the chart would show a
    number the live standings never actually showed at that point."""
    points_by_round = driver["points_by_round"]
    if "before_total" in driver:  # sim-derived entry — best-9-of-12 aware
        raced_rounds = {r for r, positions in driver["positions_by_round"].items() if positions}
        candidates = {r for r in raced_rounds if r <= upto_round}
        return _best_n_total(points_by_round, candidates)[0]
    return round(sum(v for r, v in points_by_round.items() if r <= upto_round), 1)


def get_points_progression(rows: list[dict], rounds: list[int]) -> list[dict]:
    """Cumulative points per row at each round in `rounds` — feeds the
    Championship points-progression line chart on the Drivers',
    Fantasy, and Overall tabs (Constructors' gets its own chart; see
    the standings-charts.js side). Each row's value at a given round is
    the sum of its driver_breakdown entries' own cumulative totals at
    that round (see _entry_cumulative_at), so the chart's last point
    always matches the number the standings row is currently showing.

    Returns [{"label": display_name, "car_number": ..., "participant_id":
    ..., "points": [one value per round in `rounds`, in order]}, ...] —
    `participant_id` lets the page correlate a line back to that row's
    own dropdown (see standings-charts.js's focus-on-expand behavior)."""
    return [
        {
            "label": row["display_name"],
            "car_number": row.get("car_number"),
            "participant_id": row.get("participant_id"),
            "points": [
                round(sum(_entry_cumulative_at(driver, r) for driver in row["driver_breakdown"]), 1)
                for r in rounds
            ],
        }
        for row in rows
    ]


def _attach_round_metrics(rows: list[dict], rounds: list[int], key_field: str = "participant_id") -> None:
    """Attaches this_round_points, gap_to_leader, and rank_change to
    every row, in place — shared by all 4 tabs' dropdowns. Each row's
    total as of the round before latest_round is reconstructed by
    summing (or, for Constructors' rows, blending — see
    constructor_round_points) every driver_breakdown entry's own
    before-total (see _entry_before_total), rather than subtracting the
    latest round's raw points back out directly — the two aren't always
    the same once the half-season best-9-of-12 rule is involved."""
    if not rows:
        return
    latest_round = max(rounds) if rounds else None
    leader_points = rows[0]["points"]
    before_totals = {}
    for row in rows:
        entry_befores = [_entry_before_total(driver, latest_round) for driver in row["driver_breakdown"]]
        before_total = constructor_round_points(entry_befores) if key_field == "id" else sum(entry_befores)
        before_totals[row[key_field]] = before_total
        row["this_round_points"] = round(row["points"] - before_total, 1)

    before_rank = {
        key: i + 1
        for i, (key, _) in enumerate(sorted(before_totals.items(), key=lambda kv: kv[1], reverse=True))
    }
    for i, row in enumerate(rows):
        row["gap_to_leader"] = round(leader_points - row["points"], 1)
        row["rank_change"] = before_rank[row[key_field]] - (i + 1)


def get_standings_rows(tab: str, season_id: str | None) -> tuple[list[dict], list[dict]]:
    """Returns (rows, progression) — `progression` feeds the points-
    progression line chart (see get_points_progression) and is only
    computed for the Drivers', Fantasy, and Overall tabs; Constructors'
    gets [] here since its chart (a per-team member breakdown, not a
    progression) is built straight from `rows`' driver_breakdown in the
    template instead."""
    if tab == "fantasy":
        rows = get_fantasy_only_standings(season_id)
        if season_id and rows:
            # Per-member driver/round dropdown — attached here (not
            # baked into get_fantasy_only_standings) since it's page-
            # display detail, not part of the points total itself.
            # Every row shares the same `breakdown_rounds` column list
            # so they all line up.
            from app.services.fantasy_scoring import get_fantasy_breakdown_by_participant

            breakdown_by_participant, rounds, sprint_rounds = get_fantasy_breakdown_by_participant(
                season_id
            )
            for row in rows:
                row["driver_breakdown"] = breakdown_by_participant.get(row["participant_id"], [])
                row["breakdown_rounds"] = rounds
                row["sprint_rounds"] = sprint_rounds
            _attach_round_metrics(rows, rounds)
            return rows, get_points_progression(rows, rounds)
        return rows, []
    if tab == "sim":
        rows = get_sim_only_standings(season_id)
        if season_id and rows:
            # Per-round dropdown on the Drivers' tab, same interaction as
            # the Fantasy tab's — one "driver" row (themselves) instead
            # of two drafted drivers, since a sim racer scores on their
            # own results.
            breakdown_by_participant, rounds = get_sim_breakdown_by_participant(season_id)
            for row in rows:
                # Falls back to an all-zero entry for a participant who
                # hasn't raced a round yet this season (get_sim_only_
                # standings still gives them a 0-point row) — otherwise
                # their dropdown would show as empty instead of "0 every
                # round", and their own name wouldn't appear in it.
                entry = breakdown_by_participant.get(row["participant_id"]) or {
                    "points_by_round": {rnd: 0 for rnd in rounds},
                    "positions_by_round": {rnd: [] for rnd in rounds},
                    "dropped_rounds": set(),
                    "before_total": 0,
                    "total": 0,
                }
                row["driver_breakdown"] = [
                    {**entry, "full_name": row["display_name"], "photo_url": None, "logo_url": None}
                ]
                row["breakdown_rounds"] = rounds
                row["sprint_rounds"] = set()
            _attach_round_metrics(rows, rounds)
            return rows, get_points_progression(rows, rounds)
        return rows, []
    if tab == "constructors":
        rows = get_constructor_standings(season_id)
        if season_id and rows:
            # Per-round dropdown on the Constructors' tab — one "driver"
            # row per team member, same interaction as Fantasy/Drivers'.
            breakdown_by_team, rounds = get_constructor_breakdown_by_team(season_id)
            for row in rows:
                row["driver_breakdown"] = breakdown_by_team.get(row["id"], [])
                row["breakdown_rounds"] = rounds
                row["sprint_rounds"] = set()
            _attach_round_metrics(rows, rounds, key_field="id")
        return rows, []
    rows = get_formula_fantasy_standings(season_id)
    if season_id and rows:
        # Per-round dropdown on the Overall tab — each participant's 2
        # drafted Fantasy drivers plus their own Sim Racing entry.
        breakdown_by_participant, rounds, sprint_rounds = get_overall_breakdown_by_participant(season_id)
        for row in rows:
            row["driver_breakdown"] = breakdown_by_participant.get(row["participant_id"], [])
            row["breakdown_rounds"] = rounds
            row["sprint_rounds"] = sprint_rounds
        _attach_round_metrics(rows, rounds)
        return rows, get_points_progression(rows, rounds)
    return rows, []
