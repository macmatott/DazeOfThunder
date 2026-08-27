"""
iRacing race-results JSON ingestion — an admin uploads the "event result"
JSON export straight from iRacing after each league race (replaces the
older CSV export format: JSON carries the same data plus real Strength
of Field for our Hosted-session races, real qualifying results, and the
event id in the body instead of only the filename).

Corrections follow the "supersede, never mutate" model race_events was
built for: a bad import isn't edited or deleted, it's flagged
is_superseded and the corrected re-upload points back at it via
superseded_by_id — so results/scores computed under a since-corrected
import stay in the audit trail instead of silently disappearing.

Writes use admin_client() (service_role) — every caller here is a route
that already verified the requester via the signed session cookie.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.db.supabase_client import admin_client
from app.services.fantasy_scoring import get_active_points_table, points_for_position
from app.services.participants import list_iracing_cust_id_lookup

RACE_SESSION_TYPE = 6
QUALIFY_SESSION_TYPE = 4

# iRacing's sentinel for "this isn't tied to an official series season"
# (a Hosted session, this league's actual race format) — season_year/
# season_quarter/race_week_num all come back as placeholder values
# (2000/1/0) rather than being absent, so they're only trustworthy when
# season_id isn't this sentinel.
HOSTED_SEASON_ID_SENTINEL = 0

# Columns race_results actually has — explicit whitelist rather than a
# blind dict-spread, since the parsed row also carries car_class_id
# (needed by team_event_results.py for multiclass ranking, not stored
# on race_results itself).
RACE_RESULT_COLUMNS = [
    "finish_position",
    "iracing_cust_id",
    "iracing_display_name",
    "start_position",
    "car_name",
    "car_class",
    "car_number",
    "status",
    "interval",
    "laps_led",
    "laps_completed",
    "incidents",
    "qualify_time",
    "average_lap_time",
    "fastest_lap_time",
    "fastest_lap_number",
    "iracing_points",
    "iracing_club_points",
    "old_irating",
    "new_irating",
    "is_ai",
    "participant_id",
]

# Columns race_events actually has — same explicit-whitelist reasoning
# as RACE_RESULT_COLUMNS: the parsed event dict also carries
# split_number/split_total (needed by team_event_results.py for a big
# multi-split enduro like a 24-hour race split across several parallel
# fields), which race_events has no use for.
RACE_EVENT_COLUMNS = [
    "iracing_event_id",
    "track",
    "series",
    "start_time",
    "iracing_season_year",
    "iracing_season_quarter",
    "race_week",
    "strength_of_field",
    "special_event_type",
    "season_id",
    "ff_round_number",
    "ff_round_name",
    "source_filename",
    "imported_by",
    "imported_at",
]


class JsonParseError(ValueError):
    pass


class DuplicateEventError(ValueError):
    pass


class RoundAlreadyImportedError(ValueError):
    pass


def _ticks_to_time_str(value: int | None) -> str | None:
    """iRacing JSON lap/interval times are ints in ten-thousandths of a
    second (e.g. 953812 -> "1:35.381"). -1 (or missing) means "no time
    set". Truncated, not rounded — confirmed against a real CSV/JSON
    export pair for the same race that iRacing's own CSV export
    truncates (987708 -> "1:38.770", not the correctly-rounded
    "1:38.771"), so this matches that existing convention rather than
    silently disagreeing with it on the last digit."""
    if value is None or value < 0:
        return None
    total_ms = value // 10
    minutes, rest_ms = divmod(total_ms, 60_000)
    seconds, millis = divmod(rest_ms, 1000)
    if minutes:
        return f"{minutes}:{seconds:02d}.{millis:03d}"
    return f"{seconds:02d}.{millis:03d}"


def _format_interval(value: int, *, leader_laps: int, driver_laps: int) -> str | None:
    """0 -> "-00.000" (the leader, falls out of _ticks_to_time_str
    naturally). A positive value is the gap in ten-thousandths of a
    second -> "-SS.mmm"/"-M:SS.mmm". -1 is iRacing's sentinel for "not
    on the lead lap" — there's no gap-time equivalent for that, so it's
    computed as a lap-down count against the race leader instead
    (e.g. "-2 L"), same convention iRacing's own CSV export uses."""
    if value == -1:
        laps_down = leader_laps - driver_laps
        return f"-{laps_down} L" if laps_down > 0 else None
    time_str = _ticks_to_time_str(value)
    return f"-{time_str}" if time_str is not None else None


def _select_session(session_results: list[dict], simsession_type: int) -> dict | None:
    return next((s for s in session_results if s.get("simsession_type") == simsession_type), None)


def _flatten_session_results(results: list[dict]) -> list[dict]:
    """A solo race's session results are already one flat per-cust_id
    entry each. A TEAM race's own entries are keyed by team_id instead
    (car-level stats, no cust_id of its own) with a nested
    driver_results list — one entry per co-driver, each already shaped
    exactly like a solo entry (same fields, its own cust_id, and the
    whole crew shares the car's finish_position/interval/etc.).
    Flattening here means every downstream function only ever has to
    handle the solo shape."""
    flat = []
    for row in results:
        driver_results = row.get("driver_results")
        flat.extend(driver_results) if driver_results is not None else flat.append(row)
    return flat


def _build_qualify_lookup(session_results: list[dict]) -> dict[int, int]:
    """cust_id -> best qualifying lap (ticks). Real per-driver qualifying
    times/positions live in their own "Lone Qualifying" session, not the
    Race session (whose own qual_lap_time field is always -1/unused) —
    a genuine improvement over the CSV export, whose Qualify Time column
    is blank for every driver in a real Hosted-session export we
    checked. Missing entirely (no qualifying session in this event) is
    not an error — just an empty lookup, same as "nobody has a quali
    time"."""
    qualify = _select_session(session_results, QUALIFY_SESSION_TYPE)
    if not qualify:
        return {}
    rows = _flatten_session_results(qualify.get("results", []))
    return {r["cust_id"]: r.get("best_qual_lap_time", -1) for r in rows}


def _compute_split_info(data: dict) -> tuple[int | None, int | None]:
    """A big enduro (24 Hours of Spa, say) is too large for one iRacing
    session, so it's split into several parallel fields of similar
    strength — session_splits lists every split for the whole event,
    ordered strongest-field-first, each tagged with its own
    subsession_id. Our own subsession's 1-indexed position in that list
    is "which split we raced in" (e.g. "Split 2/6"); None/None if
    there's only one (or the id isn't found, which shouldn't happen)."""
    splits = data.get("session_splits") or []
    if len(splits) < 2:
        return None, None
    split_ids = [s["subsession_id"] for s in splits]
    subsession_id = data["subsession_id"]
    if subsession_id not in split_ids:
        return None, None
    return split_ids.index(subsession_id) + 1, len(split_ids)


def _parse_event_block_json(data: dict) -> dict:
    track = data["track"]
    is_hosted = data.get("season_id", HOSTED_SEASON_ID_SENTINEL) == HOSTED_SEASON_ID_SENTINEL
    special_event_text = (data.get("race_summary") or {}).get("special_event_type_text")
    split_number, split_total = _compute_split_info(data)
    return {
        "iracing_event_id": data["subsession_id"],
        "track": f"{track['track_name']} - {track['config_name']}",
        "series": data["series_name"],
        "start_time": data["start_time"],
        # Official-series-only fields — a Hosted session (this league's
        # actual race format) reports placeholder season/week values
        # (season_id 0, season_year 2000, etc.) rather than leaving them
        # absent like the CSV export did, so they're nulled out here to
        # match — otherwise the schedule page would show a bogus
        # "Season 2000 S1" badge on every race.
        "iracing_season_year": None if is_hosted else data.get("season_year"),
        "iracing_season_quarter": None if is_hosted else data.get("season_quarter"),
        "race_week": None if is_hosted else data.get("race_week_num"),
        # Unlike the above, real for Hosted sessions too — the CSV
        # export simply never had a Strength of Field column for a
        # Hosted race, not because the data doesn't exist.
        "strength_of_field": data.get("event_strength_of_field"),
        "special_event_type": (
            None if special_event_text in (None, "Not a special event") else special_event_text
        ),
        # Not a race_events column — carried through only for
        # team_event_results.py, dropped before the race_events insert
        # via RACE_EVENT_COLUMNS.
        "split_number": split_number,
        "split_total": split_total,
    }


def _parse_result_row_json(row: dict, *, leader_laps: int, qualify_lookup: dict[int, int]) -> dict:
    best_lap_ticks = row.get("best_lap_time")
    fastest_lap_time = _ticks_to_time_str(best_lap_ticks)
    qual_ticks = qualify_lookup.get(row["cust_id"])
    return {
        "finish_position": row["finish_position"] + 1,
        "iracing_cust_id": row["cust_id"],
        "iracing_display_name": row["display_name"],
        "start_position": row["starting_position"] + 1,
        "car_name": row.get("car_name"),
        "car_class": row.get("car_class_name"),
        # Not a race_results column — carried through only for
        # team_event_results.py's per-class ranking, dropped before the
        # race_results insert via RACE_RESULT_COLUMNS.
        "car_class_id": row.get("car_class_id"),
        "car_number": (row.get("livery") or {}).get("car_number"),
        "status": row["reason_out"],
        "interval": _format_interval(
            row["interval"], leader_laps=leader_laps, driver_laps=row.get("laps_complete", 0)
        ),
        "laps_led": row.get("laps_lead", 0),
        "laps_completed": row.get("laps_complete", 0),
        "incidents": row.get("incidents", 0),
        "qualify_time": _ticks_to_time_str(qual_ticks) if qual_ticks is not None else None,
        "average_lap_time": _ticks_to_time_str(row.get("average_lap")),
        "fastest_lap_time": fastest_lap_time,
        "fastest_lap_number": row.get("best_lap_num") if fastest_lap_time is not None else None,
        # iRacing's own native points/iRating — reference data only, not
        # used for league scoring (compute_sim_scores scores off
        # finish_position instead). Real for a Hosted session in the
        # JSON (unlike the CSV export, which never had these columns
        # for a Hosted race) — kept for future use even though nothing
        # reads them today.
        "iracing_points": row.get("league_points"),
        "iracing_club_points": None,
        "old_irating": row.get("oldi_rating"),
        "new_irating": row.get("newi_rating"),
        "is_ai": bool(row.get("ai", False)),
    }


def parse_event_json(json_bytes: bytes) -> dict:
    """{"event": {...}, "results": [...]} — same shape the CSV parser
    used to produce, so match_participants/compute_sim_scores need no
    changes regardless of source format."""
    try:
        payload = json.loads(json_bytes)
    except ValueError as exc:
        raise JsonParseError(f"Not valid JSON: {exc}") from exc

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or payload.get("type") != "event_result" or not data:
        raise JsonParseError(
            "Doesn't look like an iRacing event-result export "
            "(expected a top-level {\"type\": \"event_result\", \"data\": {...}})."
        )

    try:
        session_results = data.get("session_results") or []
        race_session = _select_session(session_results, RACE_SESSION_TYPE)
        if not race_session or not race_session.get("results"):
            raise JsonParseError("No Race session results found in this export.")

        race_rows = _flatten_session_results(race_session["results"])
        qualify_lookup = _build_qualify_lookup(session_results)
        leader_laps = max((r.get("laps_complete", 0) for r in race_rows), default=0)

        return {
            "event": _parse_event_block_json(data),
            "results": [
                _parse_result_row_json(r, leader_laps=leader_laps, qualify_lookup=qualify_lookup)
                for r in race_rows
            ],
        }
    except KeyError as exc:
        raise JsonParseError(f"Export is missing an expected field: {exc}") from exc


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


def import_race_json(
    json_bytes: bytes,
    filename: str,
    *,
    season_id: str,
    ff_round_number: int,
    ff_round_name: str | None,
    imported_by: str,
    supersede: bool = False,
) -> dict:
    parsed = parse_event_json(json_bytes)
    event_id = parsed["event"]["iracing_event_id"]

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
        "ff_round_number": ff_round_number,
        "ff_round_name": ff_round_name,
        "source_filename": filename,
        "imported_by": imported_by,
        "imported_at": datetime.now(timezone.utc).isoformat(),
    }
    new_event = (
        client.table("race_events")
        .insert({k: event_row[k] for k in RACE_EVENT_COLUMNS})
        .execute()
        .data[0]
    )

    if existing and supersede:
        client.table("race_events").update(
            {"is_superseded": True, "superseded_by_id": new_event["id"]}
        ).eq("id", existing["id"]).execute()

    result_rows = [
        {**{k: r[k] for k in RACE_RESULT_COLUMNS}, "race_event_id": new_event["id"]}
        for r in matched
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
