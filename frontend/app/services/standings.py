"""
Formula Fantasy combined standings.

Deliberately simple for now: sum sim_points_awarded and fantasy_points_awarded
per participant, in Python, rather than a materialized view. Once real data
and real load exist this is a natural candidate for a Postgres view, but
there's no reason to build that before there's data to test it against —
see /docs/architecture.md on avoiding premature optimization here.

NOTE: this does not yet implement the Formula Fantasy weighting decision
(direct addition vs. normalized/percentage-based) — that's still an open
question. This currently does direct addition as a placeholder.
"""

from collections import defaultdict

from app.db.supabase_client import public_client


def _get_participant_names(client) -> dict[str, str]:
    participants = client.table("participants").select("id, display_name").execute()
    return {p["id"]: p["display_name"] for p in participants.data}


def _build_standings(rows_by_source: list[list[dict]], names: dict[str, str]) -> list[dict]:
    """Sums points across however many raw point-row lists are given (each
    row has participant_id, points), one participant per output row,
    sorted descending."""
    totals: dict[str, float] = defaultdict(float)
    for rows in rows_by_source:
        for row in rows:
            totals[row["participant_id"]] += row["points"]

    standings = [
        {"display_name": names.get(pid, "Unknown"), "points": round(points, 1)}
        for pid, points in totals.items()
    ]
    standings.sort(key=lambda row: row["points"], reverse=True)
    return standings


def get_formula_fantasy_standings(season_id: str | None = None) -> list[dict]:
    """
    Overall Championship — sim racing + fantasy F1 points combined.
    Returns [{"display_name": ..., "points": ...}, ...] sorted descending.
    Empty list if there's no season yet or nothing has been scored.
    """
    client = public_client()
    names = _get_participant_names(client)

    sim_query = client.table("sim_points_awarded").select("participant_id, points")
    fantasy_query = client.table("fantasy_points_awarded").select("participant_id, points")
    if season_id:
        # sim_points_awarded links to season via race_events; filtering by
        # season_id directly isn't available on this table without a join,
        # so full season scoping is deferred until there's a season to test
        # against. fantasy_points_awarded does carry season_id directly.
        fantasy_query = fantasy_query.eq("season_id", season_id)

    return _build_standings(
        [sim_query.execute().data, fantasy_query.execute().data], names
    )


def get_fantasy_only_standings(season_id: str | None = None) -> list[dict]:
    """Fantasy Championship — fantasy_points_awarded only, no sim racing."""
    client = public_client()
    names = _get_participant_names(client)

    fantasy_query = client.table("fantasy_points_awarded").select("participant_id, points")
    if season_id:
        fantasy_query = fantasy_query.eq("season_id", season_id)

    return _build_standings([fantasy_query.execute().data], names)
