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


def get_formula_fantasy_standings(season_id: str | None = None) -> list[dict]:
    """
    Returns [{"display_name": ..., "points": ...}, ...] sorted descending.
    Empty list if there's no season yet or nothing has been scored.
    """
    client = public_client()

    totals: dict[str, float] = defaultdict(float)
    names: dict[str, str] = {}

    participants = client.table("participants").select("id, display_name").execute()
    for p in participants.data:
        names[p["id"]] = p["display_name"]

    sim_query = client.table("sim_points_awarded").select("participant_id, points")
    fantasy_query = client.table("fantasy_points_awarded").select("participant_id, points")
    if season_id:
        # sim_points_awarded links to season via race_events; filtering by
        # season_id directly isn't available on this table without a join,
        # so full season scoping is deferred until there's a season to test
        # against. fantasy_points_awarded does carry season_id directly.
        fantasy_query = fantasy_query.eq("season_id", season_id)

    for row in sim_query.execute().data:
        totals[row["participant_id"]] += row["points"]
    for row in fantasy_query.execute().data:
        totals[row["participant_id"]] += row["points"]

    standings = [
        {"display_name": names.get(pid, "Unknown"), "points": round(points, 1)}
        for pid, points in totals.items()
    ]
    standings.sort(key=lambda row: row["points"], reverse=True)
    return standings
