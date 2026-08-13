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


def _pair_points(pair: dict, sim_totals: dict[str, float]) -> float:
    """Sum of both members' Sim Racing points — Constructors' scoring is
    explicitly Sim-Racing-only per ff_how_it_works.html's published copy
    ("Your team's combined Sim Racing results carry the Constructors'
    Championship"), not the Overall sim+fantasy blend."""
    return round(
        sum(sim_totals.get(m["participant_id"], 0.0) for m in pair["constructor_members"]), 1
    )


def get_constructor_standings(season_id: str | None) -> list[dict]:
    """Constructors' Championship — each formed pair's combined season Sim
    Racing points. One row per pair; a pair shows once formed even at 0
    points. Empty only before the constructor draft has paired anyone."""
    if not season_id:
        return []
    client = admin_client()
    sim_totals = _get_sim_totals(client, season_id)
    pairs = get_pairs(season_id)

    standings = [
        {
            "display_name": pair["name"] or pair["member_names"],
            "role": None,
            "points": _pair_points(pair, sim_totals),
            "logo_url": pair["logo_url"],
        }
        for pair in pairs
    ]
    standings.sort(key=lambda row: row["points"], reverse=True)
    return standings


def get_standings_rows(tab: str, season_id: str | None) -> list[dict]:
    if tab == "fantasy":
        return get_fantasy_only_standings(season_id)
    if tab == "sim":
        return get_sim_only_standings(season_id)
    if tab == "constructors":
        return get_constructor_standings(season_id)
    return get_formula_fantasy_standings(season_id)
