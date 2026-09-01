"""
Team Event race results — an admin uploads the same iRacing JSON export
used elsewhere on the site (see iracing_ingest.py) against a specific
Team Event, and only the rows matching our own registered members are
kept, purely for display on that event's card (who raced, how they
qualified/finished, laps, incidents, lap times). Unlike race_results,
this has no scoring or audit-trail purpose, so a re-upload just
replaces the prior rows outright rather than superseding them.

Team Events are often multiclass races, where the export's own overall
finish/start positions span every class — not what "how did our team
do" means when GT3 and LMP2 (say) are racing at the same time.
finish_position/start_position stored here are therefore recomputed as
rank-within-car-class (via each row's car_class_id, which
parse_event_json carries through specifically for this), not copied
from the overall positions. This is a no-op in a single-class race,
since rank-within-the-only-class equals the overall rank.

Writes use admin_client() (service_role) — every caller here is a
route that already verified the requester via the signed session
cookie.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.db.supabase_client import admin_client
from app.services.f1_schedule import _parse_lap_time_seconds
from app.services.iracing_ingest import JsonParseError, match_participants, parse_event_json
from app.services.participants import list_iracing_cust_id_lookup

__all__ = ["JsonParseError", "get_team_event_results", "import_team_event_results"]


def _compute_class_standings(results: list[dict]) -> dict[int, dict]:
    """{cust_id: {"finish_position": rank-within-class, "start_position":
    rank-within-class}} — every entrant in the export (not just our
    members) is ranked, since a car's class position depends on where
    its class-mates outside our roster finished/qualified too.

    Team races have one result row per co-driver, all sharing their
    car's one overall finish/start position — ranking must be dense
    over the *distinct* position values within the class, not over
    every row, or a multi-driver team inflates its own class rank
    (e.g. a 3-driver car pushes every class-mate behind it 3 ranks
    lower instead of 1)."""
    by_class: dict[int | None, list[dict]] = {}
    for r in results:
        by_class.setdefault(r.get("car_class_id"), []).append(r)

    standings: dict[int, dict] = {}
    for rows in by_class.values():
        for field in ("finish_position", "start_position"):
            distinct_positions = sorted({r[field] for r in rows})
            rank_by_position = {pos: rank for rank, pos in enumerate(distinct_positions, start=1)}
            for r in rows:
                standings.setdefault(r["iracing_cust_id"], {})[field] = rank_by_position[r[field]]
    return standings


def import_team_event_results(
    team_event_id: str, json_bytes: bytes, filename: str, imported_by: str
) -> dict:
    parsed = parse_event_json(json_bytes)
    class_standings = _compute_class_standings(parsed["results"])

    cust_id_lookup = list_iracing_cust_id_lookup()
    matched = match_participants(parsed["results"], cust_id_lookup)
    member_rows = [r for r in matched if r["participant_id"] and not r["is_ai"]]

    client = admin_client()
    client.table("team_event_results").delete().eq("team_event_id", team_event_id).execute()

    if member_rows:
        imported_at = datetime.now(timezone.utc).isoformat()
        rows = [
            {
                "team_event_id": team_event_id,
                "participant_id": r["participant_id"],
                "finish_position": class_standings[r["iracing_cust_id"]]["finish_position"],
                "start_position": class_standings[r["iracing_cust_id"]]["start_position"],
                "car_name": r["car_name"],
                "laps_completed": r["laps_completed"],
                "incidents": r["incidents"],
                "average_lap_time": r["average_lap_time"],
                "fastest_lap_time": r["fastest_lap_time"],
                "session_start_time": parsed["event"]["start_time"],
                "split_number": parsed["event"]["split_number"],
                "split_total": parsed["event"]["split_total"],
                "strength_of_field": parsed["event"]["strength_of_field"],
                "source_filename": filename,
                "imported_by": imported_by,
                "imported_at": imported_at,
            }
            for r in member_rows
        ]
        client.table("team_event_results").insert(rows).execute()

    return {
        "total_rows": len(parsed["results"]),
        "matched_count": len(member_rows),
    }


def _mark_best(rows: list[dict], *, time_field: str, flag_field: str) -> None:
    """Flags whichever row has the lowest time_field (parsed via
    _parse_lap_time_seconds) with flag_field = True, every other row
    False. Shared by the fastest-lap and best-average-lap markers below
    — same "single best of our own crew" idea, just against a different
    time column."""
    for row in rows:
        row[flag_field] = False
    timed = [
        (i, seconds)
        for i, row in enumerate(rows)
        if (seconds := _parse_lap_time_seconds(row[time_field])) is not None
    ]
    if timed:
        best_index, _ = min(timed, key=lambda pair: pair[1])
        rows[best_index][flag_field] = True


def _mark_least(rows: list[dict], *, field: str, flag_field: str) -> None:
    """Flags whichever row has the lowest plain numeric field (e.g.
    incidents) with flag_field = True — same "single best of our own
    crew" idea as _mark_best, just for a value that's already a number
    rather than a lap time needing parsing."""
    for row in rows:
        row[flag_field] = False
    if rows:
        least_index = min(range(len(rows)), key=lambda i: rows[i][field])
        rows[least_index][flag_field] = True


def get_team_event_results(team_event_id: str) -> list[dict]:
    """team_event_results has two FKs into participants (participant_id
    and imported_by), so the embed must name which relationship to
    follow — an unqualified participants(...) is ambiguous to
    PostgREST. Aliased back to "participants" so callers/templates
    don't need to know about the underlying constraint name.

    Also marks whichever of our own co-drivers set the fastest lap
    (is_fastest_lap), the best average lap (is_best_avg_lap), and the
    fewest incidents (has_least_incidents) — called out on the card,
    same "single best of our own crew" convention throughout, since
    this table only ever stores our own members' rows, never the whole
    field."""
    client = admin_client()
    rows = (
        client.table("team_event_results")
        .select(
            "finish_position, start_position, car_name, laps_completed, incidents, "
            "average_lap_time, fastest_lap_time, session_start_time, split_number, split_total, "
            "strength_of_field, "
            "participants:participants!team_event_results_participant_id_fkey(display_name, role, car_number)"
        )
        .eq("team_event_id", team_event_id)
        .order("finish_position")
        .execute()
        .data
    )

    _mark_best(rows, time_field="fastest_lap_time", flag_field="is_fastest_lap")
    _mark_best(rows, time_field="average_lap_time", flag_field="is_best_avg_lap")
    _mark_least(rows, field="incidents", flag_field="has_least_incidents")

    return rows
