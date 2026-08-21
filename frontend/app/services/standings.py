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
"""

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


def _get_participants(client) -> dict[str, dict]:
    participants = client.table("participants").select("id, display_name, role").execute()
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
    unknown = {"display_name": "Unknown", "role": "member"}
    standings = [
        {
            "participant_id": pid,
            "display_name": participants.get(pid, unknown)["display_name"],
            "role": participants.get(pid, unknown)["role"],
            "points": round(points, 1),
        }
        for pid, points in totals.items()
    ]
    standings.sort(key=lambda row: row["points"], reverse=True)
    return standings


def _build_standings(rows_by_source: list[list[dict]], participants: dict[str, dict]) -> list[dict]:
    return _rows_from_totals(_sum_points(rows_by_source), participants)


def _get_sim_totals(client, season_id: str | None = None) -> dict[str, float]:
    # sim_points_awarded links to season via race_events, not a direct
    # season_id column — full season scoping is deferred until there's a
    # season boundary to test against (same caveat as before this file's
    # rewrite), so season_id is accepted for API symmetry but unused here.
    sim_query = client.table("sim_points_awarded").select("participant_id, points")
    return _sum_points([sim_query.execute().data])


def get_formula_fantasy_standings(season_id: str | None = None) -> list[dict]:
    """
    Overall Championship — sim racing + fantasy F1 points combined.
    Returns [{"display_name": ..., "role": ..., "points": ...}, ...]
    sorted descending. Empty list if there's no season yet or nothing
    has been scored.
    """
    client = admin_client()
    participants = _get_participants(client)

    fantasy_query = client.table("fantasy_points_awarded").select("participant_id, points")
    if season_id:
        fantasy_query = fantasy_query.eq("season_id", season_id)

    sim_totals = _get_sim_totals(client, season_id)
    fantasy_totals = _sum_points([fantasy_query.execute().data])

    combined: dict[str, float] = defaultdict(float)
    for pid, points in sim_totals.items():
        combined[pid] += points
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
    """Drivers' Championship — sim_points_awarded only, no fantasy."""
    client = admin_client()
    participants = _get_participants(client)
    return _rows_from_totals(_get_sim_totals(client, season_id), participants)


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

    Returns ({participant_id: {"points_by_round": {round_number:
    points}, "positions_by_round": {round_number: [finish_position]},
    "total"}}, rounds) — `rounds` is every ff_round_number with a scored
    (non-superseded) race_event this season, ascending."""
    if not season_id:
        return {}, []
    client = admin_client()
    points_by_participant, positions_by_participant, rounds = _get_sim_results_by_round(client, season_id)
    if not rounds:
        return {}, []

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
        breakdown[participant_id] = {
            "points_by_round": points_by_round,
            "positions_by_round": positions_by_round,
            "total": round(sum(points_by_round.values()), 1),
        }

    return breakdown, rounds


def get_constructor_breakdown_by_team(season_id: str | None) -> tuple[dict[str, list[dict]], list[int]]:
    """Per-round sim points/finish position for every constructor team's
    own members — feeds the Constructors' standings page's per-team
    dropdown, the same interaction as Fantasy/Drivers' but with one
    "driver" row per team member.

    A team's actual per-round score only counts its best 2 scorers that
    round (see _pair_points above) — this league's one 3-person team has
    its lowest-scoring member each round marked via that member's
    dropped_rounds set, so the table can flag it (and each member's own
    `total` only sums the rounds that counted, so the three members'
    totals still add up to the team's real standings total)."""
    if not season_id:
        return {}, []
    client = admin_client()
    points_by_participant, positions_by_participant, rounds = _get_sim_results_by_round(client, season_id)
    if not rounds:
        return {}, []

    pairs = get_pairs(season_id)
    breakdown: dict[str, list[dict]] = {}
    for pair in pairs:
        member_ids = [m["participant_id"] for m in pair["constructor_members"]]

        dropped_by_member: dict[str, set[int]] = defaultdict(set)
        for rnd in rounds:
            ranked = sorted(
                member_ids,
                key=lambda pid: points_by_participant.get(pid, {}).get(rnd, 0.0),
                reverse=True,
            )
            for pid in ranked[2:]:
                dropped_by_member[pid].add(rnd)

        members_breakdown = []
        for member in pair["constructor_members"]:
            pid = member["participant_id"]
            dropped_rounds = dropped_by_member.get(pid, set())
            points_by_round = {rnd: points_by_participant.get(pid, {}).get(rnd, 0) for rnd in rounds}
            positions_by_round = {
                rnd: (
                    [positions_by_participant[pid][rnd]]
                    if rnd in positions_by_participant.get(pid, {})
                    else []
                )
                for rnd in rounds
            }
            members_breakdown.append(
                {
                    "full_name": member["participants"]["display_name"],
                    "photo_url": None,
                    "logo_url": None,
                    "points_by_round": points_by_round,
                    "positions_by_round": positions_by_round,
                    "dropped_rounds": dropped_rounds,
                    "total": round(
                        sum(pts for rnd, pts in points_by_round.items() if rnd not in dropped_rounds), 1
                    ),
                }
            )
        breakdown[pair["id"]] = members_breakdown

    return breakdown, rounds


def _get_sim_points_by_round(client) -> dict[str, dict[str, float]]:
    """race_event_id -> {participant_id: points}, for _pair_points' per-
    round best-2-of-team scoring below."""
    rows = client.table("sim_points_awarded").select("participant_id, points, race_event_id").execute().data
    by_round: dict[str, dict[str, float]] = defaultdict(dict)
    for row in rows:
        by_round[row["race_event_id"]][row["participant_id"]] = row["points"]
    return by_round


def _pair_points(pair: dict, points_by_round: dict[str, dict[str, float]]) -> float:
    """Sum, across every scored round, of the team's best 2 contributors
    that round — Constructors' scoring is explicitly Sim-Racing-only per
    ff_how_it_works.html's published copy ("Your team's combined Sim
    Racing results carry the Constructors' Championship"), not the
    Overall sim+fantasy blend.

    This league has one team of 3 (odd number of members); capping every
    team at its best 2 scorers per round — rather than summing all of a
    3-person team's results — keeps a 3-person team from getting an
    extra scoring opportunity every race that 2-person teams don't get.
    Which member gets dropped can change round to round, since it's
    whoever scored lowest that specific race, not fixed for the season."""
    member_ids = [m["participant_id"] for m in pair["constructor_members"]]
    total = 0.0
    for round_points in points_by_round.values():
        scores = sorted((round_points.get(pid, 0.0) for pid in member_ids), reverse=True)
        total += sum(scores[:2])
    return round(total, 1)


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
    """Constructors' Championship — each formed pair's combined season Sim
    Racing points. One row per pair; a pair shows once formed even at 0
    points. Empty only before the constructor draft has paired anyone."""
    if not season_id:
        return []
    client = admin_client()
    points_by_round = _get_sim_points_by_round(client)
    pairs = get_pairs(season_id)

    standings = [
        {
            "id": pair["id"],
            "display_name": pair["name"] or pair["member_names"],
            "role": None,
            "points": _pair_points(pair, points_by_round),
            "logo_url": pair["logo_url"],
        }
        for pair in pairs
    ]
    standings.sort(key=lambda row: row["points"], reverse=True)
    return standings


def get_standings_rows(tab: str, season_id: str | None) -> list[dict]:
    if tab == "fantasy":
        rows = get_fantasy_only_standings(season_id)
        if season_id and rows:
            # Per-member driver/round dropdown on the Fantasy tab only —
            # attached here (not baked into get_fantasy_only_standings)
            # since it's page-display detail, not part of the points
            # total itself. Every row shares the same `breakdown_rounds`
            # column list so they all line up.
            from app.services.fantasy_scoring import get_fantasy_breakdown_by_participant

            breakdown_by_participant, rounds, sprint_rounds = get_fantasy_breakdown_by_participant(
                season_id
            )
            for row in rows:
                row["driver_breakdown"] = breakdown_by_participant.get(row["participant_id"], [])
                row["breakdown_rounds"] = rounds
                row["sprint_rounds"] = sprint_rounds

            # "This round's gain" + rank movement since before that round,
            # reconstructed by subtracting the latest round's points back
            # out of each row's total — no separate history/snapshot table
            # needed since fantasy_points_awarded is already broken out
            # per round via driver_breakdown.
            latest_round = max(rounds) if rounds else None
            leader_points = rows[0]["points"]
            before_totals = {}
            for row in rows:
                gained = sum(
                    driver["points_by_round"].get(latest_round, 0)
                    for driver in row["driver_breakdown"]
                ) if latest_round is not None else 0
                row["this_round_points"] = round(gained, 1)
                before_totals[row["participant_id"]] = row["points"] - gained

            before_rank = {
                pid: i + 1
                for i, (pid, _) in enumerate(
                    sorted(before_totals.items(), key=lambda kv: kv[1], reverse=True)
                )
            }
            for i, row in enumerate(rows):
                row["gap_to_leader"] = round(leader_points - row["points"], 1)
                row["rank_change"] = before_rank[row["participant_id"]] - (i + 1)
        return rows
    if tab == "sim":
        rows = get_sim_only_standings(season_id)
        if season_id and rows:
            # Per-round dropdown on the Drivers' tab, same interaction as
            # the Fantasy tab's — one "driver" row (themselves) instead
            # of two drafted drivers, since a sim racer scores on their
            # own results.
            breakdown_by_participant, rounds = get_sim_breakdown_by_participant(season_id)
            for row in rows:
                entry = breakdown_by_participant.get(row["participant_id"])
                row["driver_breakdown"] = (
                    [{**entry, "full_name": row["display_name"], "photo_url": None, "logo_url": None}]
                    if entry
                    else []
                )
                row["breakdown_rounds"] = rounds
                row["sprint_rounds"] = set()
        return rows
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
        return rows
    rows = get_formula_fantasy_standings(season_id)
    if season_id and rows:
        # Per-round dropdown on the Overall tab — each participant's 2
        # drafted Fantasy drivers plus their own Sim Racing entry.
        breakdown_by_participant, rounds, sprint_rounds = get_overall_breakdown_by_participant(season_id)
        for row in rows:
            row["driver_breakdown"] = breakdown_by_participant.get(row["participant_id"], [])
            row["breakdown_rounds"] = rounds
            row["sprint_rounds"] = sprint_rounds
    return rows
