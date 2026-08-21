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
            # total itself. Every row shares the same `fantasy_rounds`
            # column list so they all line up.
            from app.services.fantasy_scoring import get_fantasy_breakdown_by_participant

            breakdown_by_participant, rounds, sprint_rounds = get_fantasy_breakdown_by_participant(
                season_id
            )
            for row in rows:
                row["driver_breakdown"] = breakdown_by_participant.get(row["participant_id"], [])
                row["fantasy_rounds"] = rounds
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
        return get_sim_only_standings(season_id)
    if tab == "constructors":
        return get_constructor_standings(season_id)
    return get_formula_fantasy_standings(season_id)
