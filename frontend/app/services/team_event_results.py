"""
Team Event race results — an admin uploads the same iRacing CSV export
used elsewhere on the site (see iracing_ingest.py) against a specific
Team Event, and only the rows matching our own registered members are
kept, purely for display on that event's card (who raced, how they
qualified/finished, laps, incidents, lap times). Unlike race_results,
this has no scoring or audit-trail purpose, so a re-upload just
replaces the prior rows outright rather than superseding them.

Team Events are often multiclass races, where the CSV's own Fin
Pos/Start Pos are overall-field positions spanning every class — not
what "how did our team do" means when GT3 and LMP2 (say) are racing
at the same time. finish_position/start_position stored here are
therefore recomputed as rank-within-car-class (via the CSV's "Car
Class ID" column), not copied from the CSV's raw Fin Pos/Start Pos.
This is a no-op in a single-class race, since rank-within-the-only-
class equals the overall rank.

Writes use admin_client() (service_role) — every caller here is a
route that already verified the requester via the signed session
cookie.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from app.db.supabase_client import admin_client
from app.services.iracing_ingest import (
    CsvParseError,
    match_participants,
    parse_event_csv,
    split_event_and_result_blocks,
)
from app.services.participants import list_iracing_cust_id_lookup

__all__ = ["CsvParseError", "get_team_event_results", "import_team_event_results"]


def _parse_car_class_ids(csv_text: str) -> dict[int, str]:
    """Cust ID -> Car Class ID, read straight from the CSV's raw result
    block — parse_event_csv's typed rows don't carry this column
    through (race_results has no use for it)."""
    _, results_text = split_event_and_result_blocks(csv_text)
    return {
        int(row["Cust ID"]): row["Car Class ID"]
        for row in csv.DictReader(io.StringIO(results_text))
    }


def _compute_class_standings(
    results: list[dict], cust_id_to_class: dict[int, str]
) -> dict[int, dict]:
    """{cust_id: {"finish_position": rank-within-class, "start_position":
    rank-within-class}} — every entrant in the CSV (not just our
    members) is ranked, since a car's class position depends on where
    its class-mates outside our roster finished/qualified too.

    Team races have one CSV row per co-driver, all sharing their car's
    one overall Fin Pos/Start Pos — ranking must be dense over the
    *distinct* position values within the class, not over every row,
    or a multi-driver team inflates its own class rank (e.g. a 3-driver
    car pushes every class-mate behind it 3 ranks lower instead of 1)."""
    by_class: dict[str, list[dict]] = {}
    for r in results:
        by_class.setdefault(cust_id_to_class.get(r["iracing_cust_id"]), []).append(r)

    standings: dict[int, dict] = {}
    for rows in by_class.values():
        for field in ("finish_position", "start_position"):
            distinct_positions = sorted({r[field] for r in rows})
            rank_by_position = {pos: rank for rank, pos in enumerate(distinct_positions, start=1)}
            for r in rows:
                standings.setdefault(r["iracing_cust_id"], {})[field] = rank_by_position[r[field]]
    return standings


def import_team_event_results(
    team_event_id: str, csv_bytes: bytes, filename: str, imported_by: str
) -> dict:
    csv_text = csv_bytes.decode("utf-8-sig")
    parsed = parse_event_csv(csv_text)
    class_standings = _compute_class_standings(parsed["results"], _parse_car_class_ids(csv_text))

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


def get_team_event_results(team_event_id: str) -> list[dict]:
    """team_event_results has two FKs into participants (participant_id
    and imported_by), so the embed must name which relationship to
    follow — an unqualified participants(...) is ambiguous to
    PostgREST. Aliased back to "participants" so callers/templates
    don't need to know about the underlying constraint name."""
    client = admin_client()
    return (
        client.table("team_event_results")
        .select(
            "finish_position, start_position, car_name, laps_completed, incidents, "
            "average_lap_time, fastest_lap_time, "
            "participants:participants!team_event_results_participant_id_fkey(display_name, role)"
        )
        .eq("team_event_id", team_event_id)
        .order("finish_position")
        .execute()
        .data
    )
