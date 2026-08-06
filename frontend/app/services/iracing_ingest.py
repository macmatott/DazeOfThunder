"""
iRacing race-results CSV ingestion — an admin uploads the export straight
from iRacing after each league race. Two-block CSV format (confirmed
against a real export, see discord-bot/tests/fixtures/README.md): one
header + one data row of event metadata, a blank line, then a header +
one row per driver. The iRacing event id lives in the *filename*
(eventresult_<id>_0.csv), never the CSV body.

Corrections follow the "supersede, never mutate" model race_events was
built for: a bad import isn't edited or deleted, it's flagged
is_superseded and the corrected re-upload points back at it via
superseded_by_id — so results/scores computed under a since-corrected
import stay in the audit trail instead of silently disappearing.

Writes use admin_client() (service_role) — every caller here is a route
that already verified the requester via the signed session cookie.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone

from app.db.supabase_client import admin_client
from app.services.fantasy_scoring import get_active_points_table, points_for_position
from app.services.participants import list_iracing_cust_id_lookup

FILENAME_PATTERN = re.compile(r"eventresult_(\d+)_\d+\.csv", re.IGNORECASE)


class InvalidFilenameError(ValueError):
    pass


class CsvParseError(ValueError):
    pass


class DuplicateEventError(ValueError):
    pass


class RoundAlreadyImportedError(ValueError):
    pass


def parse_event_id_from_filename(filename: str) -> int:
    match = FILENAME_PATTERN.match(filename)
    if not match:
        raise InvalidFilenameError(
            f"{filename!r} doesn't look like an iRacing results export "
            "(expected a name like eventresult_87601875_0.csv)."
        )
    return int(match.group(1))


def _blank_to_none(value: str) -> str | None:
    value = value.strip()
    return value or None


def _to_int(value: str) -> int | None:
    value = value.strip()
    return int(value) if value else None


def _to_int_default(value: str, default: int = 0) -> int:
    value = value.strip()
    return int(value) if value else default


def _parse_event_block(rows: list[dict]) -> dict:
    if len(rows) != 1:
        raise CsvParseError(f"Expected exactly one event metadata row, found {len(rows)}.")
    row = rows[0]
    try:
        return {
            "track": row["Track"],
            "series": row["Series"],
            "start_time": row["Start Time"],
            "iracing_season_year": _to_int(row["Season Year"]),
            "iracing_season_quarter": _to_int(row["Season Quarter"]),
            "race_week": _to_int(row["Race Week"]),
            "strength_of_field": _to_int(row["Strength of Field"]),
            "special_event_type": _blank_to_none(row["Special Event Type"]),
        }
    except KeyError as exc:
        raise CsvParseError(f"Event metadata row is missing column {exc}.") from exc


def _parse_result_row(row: dict) -> dict:
    try:
        return {
            "finish_position": int(row["Fin Pos"]),
            "iracing_cust_id": int(row["Cust ID"]),
            "iracing_display_name": row["Name"],
            "start_position": int(row["Start Pos"]),
            "car_name": _blank_to_none(row["Car"]),
            "car_class": _blank_to_none(row["Car Class"]),
            "car_number": _blank_to_none(row["Car #"]),
            "status": row["Out"],
            "interval": _blank_to_none(row["Interval"]),
            "laps_led": _to_int_default(row["Laps Led"]),
            "laps_completed": _to_int_default(row["Laps Comp"]),
            "incidents": _to_int_default(row["Inc"]),
            "qualify_time": _blank_to_none(row["Qualify Time"]),
            "average_lap_time": _blank_to_none(row["Average Lap Time"]),
            "fastest_lap_time": _blank_to_none(row["Fastest Lap Time"]),
            "fastest_lap_number": _to_int(row["Fast Lap#"]),
            "iracing_points": _to_int(row["Pts"]),
            "iracing_club_points": _to_int(row["Club Pts"]),
            "old_irating": _to_int(row["Old iRating"]),
            "new_irating": _to_int(row["New iRating"]),
            "is_ai": row["AI"].strip() == "1",
        }
    except KeyError as exc:
        raise CsvParseError(f"Results row is missing column {exc}.") from exc


def parse_event_csv(csv_text: str) -> dict:
    """{"event": {...}, "results": [...]} — csv.DictReader is column-name
    keyed throughout, never positional, since real exports don't always
    keep columns in the same order."""
    lines = csv_text.splitlines()
    blank_indexes = [i for i, line in enumerate(lines) if not line.strip()]
    if not blank_indexes:
        raise CsvParseError("Expected a blank line separating event metadata from results.")
    blank_index = blank_indexes[0]

    event_rows = list(csv.DictReader(io.StringIO("\n".join(lines[:blank_index]))))
    result_rows = list(csv.DictReader(io.StringIO("\n".join(lines[blank_index + 1 :]))))

    if not result_rows:
        raise CsvParseError("No driver result rows found.")

    return {
        "event": _parse_event_block(event_rows),
        "results": [_parse_result_row(row) for row in result_rows],
    }


def match_participants(results: list[dict], cust_id_to_participant_id: dict[int, str]) -> list[dict]:
    return [
        {**r, "participant_id": cust_id_to_participant_id.get(r["iracing_cust_id"])}
        for r in results
    ]


def compute_sim_scores(results: list[dict], points_table: dict[int, float]) -> list[dict]:
    """Direct participant-finish -> points, no draft-pick indirection
    (unlike fantasy_scoring.compute_round_scores) — a sim racer scores
    for themselves, not on behalf of anyone who drafted them."""
    return [
        {
            "participant_id": r["participant_id"],
            "points": points_for_position(r["finish_position"], points_table),
        }
        for r in results
        if r["participant_id"] is not None and not r["is_ai"]
    ]


def get_race_event_by_iracing_event_id(event_id: int) -> dict | None:
    client = admin_client()
    result = (
        client.table("race_events").select("*").eq("iracing_event_id", event_id).execute()
    )
    return result.data[0] if result.data else None


def get_active_race_event_for_round(season_id: str, ff_round_number: int) -> dict | None:
    client = admin_client()
    result = (
        client.table("race_events")
        .select("*")
        .eq("season_id", season_id)
        .eq("ff_round_number", ff_round_number)
        .eq("is_superseded", False)
        .execute()
    )
    return result.data[0] if result.data else None


def list_recent_race_events(season_id: str, limit: int = 10) -> list[dict]:
    client = admin_client()
    return (
        client.table("race_events")
        .select(
            "id, track, series, start_time, race_week, ff_round_name, "
            "ff_round_number, is_superseded, source_filename, imported_at"
        )
        .eq("season_id", season_id)
        .order("imported_at", desc=True)
        .limit(limit)
        .execute()
        .data
    )


def import_race_csv(
    csv_bytes: bytes,
    filename: str,
    *,
    season_id: str,
    ff_round_number: int,
    ff_round_name: str | None,
    imported_by: str,
    supersede: bool = False,
) -> dict:
    event_id = parse_event_id_from_filename(filename)
    parsed = parse_event_csv(csv_bytes.decode("utf-8-sig"))

    if get_race_event_by_iracing_event_id(event_id):
        raise DuplicateEventError(f"This race (event {event_id}) has already been imported.")

    existing = get_active_race_event_for_round(season_id, ff_round_number)
    if existing and not supersede:
        raise RoundAlreadyImportedError(
            f"Round {ff_round_number} already has an uploaded race "
            f"({existing['track']}, from {existing['source_filename']}). "
            "Check \"Replace an existing import for this round\" to supersede it."
        )

    cust_id_lookup = list_iracing_cust_id_lookup()
    matched = match_participants(parsed["results"], cust_id_lookup)
    points_table, rule_version = get_active_points_table(season_id, rule_type="sim_racing")
    scores = compute_sim_scores(matched, points_table)

    client = admin_client()
    event_row = {
        **parsed["event"],
        "season_id": season_id,
        "iracing_event_id": event_id,
        "ff_round_number": ff_round_number,
        "ff_round_name": ff_round_name,
        "source_filename": filename,
        "imported_by": imported_by,
        "imported_at": datetime.now(timezone.utc).isoformat(),
    }
    new_event = client.table("race_events").insert(event_row).execute().data[0]

    if existing and supersede:
        client.table("race_events").update(
            {"is_superseded": True, "superseded_by_id": new_event["id"]}
        ).eq("id", existing["id"]).execute()

    result_rows = [
        {**r, "race_event_id": new_event["id"]} for r in matched
    ]
    client.table("race_results").insert(result_rows).execute()

    score_rows = [
        {
            "race_event_id": new_event["id"],
            "participant_id": s["participant_id"],
            "points": s["points"],
            "scoring_rule_version": rule_version,
        }
        for s in scores
    ]
    if score_rows:
        client.table("sim_points_awarded").insert(score_rows).execute()

    matched_count = sum(1 for r in matched if r["participant_id"] is not None)
    return {
        "race_event": new_event,
        "results_count": len(matched),
        "matched_count": matched_count,
        "unmatched_count": len(matched) - matched_count,
        "scored_count": len(score_rows),
        "superseded_event_id": existing["id"] if existing and supersede else None,
    }
