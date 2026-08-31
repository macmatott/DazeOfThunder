"""
F1 schedule data for the Formula Fantasy section. `get_upcoming_races`
fetches the season calendar live from Jolpica-F1 and filters to what's
still ahead (used by the landing page). `get_season_timeline` additionally
merges in real results from `f1_race_results` (used by the full-season
Schedule page) — reads go through `public_client()`, since this is
public-facing data.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.db.supabase_client import admin_client, public_client
from app.services.constructor_draft import get_pairs
from app.services.draft import logo_url_for_team
from app.services.driver_photos import driver_photo_url, slugify_name
from app.services.f1_ingest import JolpicaClient
from app.services.fantasy_scoring import (
    ScoringRulesNotSeededError,
    get_active_points_table,
    points_for_position,
    sprint_points_table,
)

TRACK_IMAGE_DIR = Path(__file__).resolve().parent.parent / "static" / "img" / "tracks"

# Placeholder sim-session weather, per round — set by league admin as real
# forecasts/conditions come in. Rounds not yet listed here fall back to the
# defaults below.
SIM_TEMPERATURE_F = 80
SIM_CONDITIONS = "No rain"

SIM_TEMPERATURE_BY_ROUND: dict[int, int] = {
    1: 72,
    2: 66,
    3: 67,
    4: 85,
    5: 67,
    6: 69,
    7: 75,
    8: 77,
    9: 67,
    10: 67,
    11: 71,
    12: 69,
    13: 84,
}
SIM_CONDITIONS_BY_ROUND: dict[int, str] = {
    1: "No rain",
    2: "No rain",
    3: "No rain",
    4: "No rain",
    5: "No rain",
    6: "No rain",
    7: "No rain",
    8: "No rain",
    9: "No rain",
    10: "No rain",
    11: "No rain",
    12: "No rain",
    13: "No rain",
}

# Real F1 race distance (laps) per round — fixed by circuit, known in
# advance regardless of whether the round has been run yet. The sim race
# runs 50% distance, rounded down for odd lap counts.
F1_LAPS_BY_ROUND: dict[int, int] = {
    1: 58,
    2: 56,
    3: 53,
    4: 57,
    5: 70,
    6: 78,
    7: 66,
    8: 71,
    9: 52,
    10: 44,
    11: 70,
    12: 72,
    13: 53,
    14: 57,
    15: 51,
    16: 57,
    17: 62,
    18: 56,
    19: 71,
    20: 71,
    21: 50,
    22: 57,
    23: 58,
}


def sim_race_laps(round_number: int) -> int | None:
    f1_laps = F1_LAPS_BY_ROUND.get(round_number)
    return f1_laps // 2 if f1_laps else None  # round down for odd F1 lap counts


# iRacing track assigned to each round's sim race — set by league admin,
# not derived from the F1 calendar. Not tied to real-world geography (the
# sim track doesn't have to match the host country).
IRACING_TRACK_BY_ROUND: dict[int, str] = {
    1: "Phillip Island Circuit",
    2: "Okayama International Circuit — Full Course",
    3: "Suzuka International Racing Course — Grand Prix",
    4: "Miami International Autodrome — Grand Prix",
    5: "Circuit Gilles Villeneuve — Grand Prix",
    6: "Adelaide Street Circuit",
    7: "Circuit de Barcelona-Catalunya — Grand Prix",
    8: "Red Bull Ring — Grand Prix",
    9: "Silverstone Circuit — Grand Prix",
    10: "Circuit de Spa-Francorchamps — Grand Prix Pits",
    11: "Hungaroring",
    12: "Circuit Park Zandvoort — Grand Prix",
    13: "Autodromo Nazionale Monza — Grand Prix",
    14: "Circuito de Navarra — Speed Circuit",
    15: "Summit Point Raceway — Summit Point Raceway",
    16: "Motorsport Arena Oschersleben — Grand Prix",
    17: "Circuit de Lédenon — Grand Prix",
    18: "Circuit of the Americas — Grand Prix",
    19: "Autódromo Hermanos Rodríguez — Grand Prix",
    20: "Autódromo José Carlos Pace — Grand Prix",
    21: "Charlotte Motor Speedway — Roval 2025",
    22: "Virginia International Raceway — Full Course",
    23: "Rudskogen Motorsenter",
}

def _get_paid_track_names() -> set[str]:
    """Track names (not round-keyed) confirmed as paid iRacing DLC, from
    the iracing_tracks table — kept by track identity rather than round
    number so a future season reusing a track on a different round picks
    up its paid/free status automatically instead of needing it
    re-entered. Only genuinely new tracks need a manual is_paid row (see
    database/schema.sql's iracing_tracks table)."""
    rows = (
        public_client()
        .table("iracing_tracks")
        .select("name")
        .eq("is_paid", True)
        .execute()
        .data
    )
    return {row["name"] for row in rows}


def _race_datetime(race: dict) -> datetime:
    date_str = race["date"]
    time = race.get("time", "00:00:00Z")
    return datetime.fromisoformat(f"{date_str}T{time}".replace("Z", "+00:00"))


def _thursday_before(race_dt: datetime) -> date:
    """Most recent Thursday on/before race_dt's date (weekday 3 = Thursday)."""
    days_since_thursday = (race_dt.weekday() - 3) % 7
    return race_dt.date() - timedelta(days=days_since_thursday)


def _split_track_name(iracing_track: str | None) -> tuple[str, str]:
    """"Circuit Park Zandvoort — Grand Prix" -> ("Circuit Park Zandvoort",
    "Grand Prix") — the track itself vs. which layout/config a round uses.
    One track image covers every config, so only the first half matters
    there; the session detail popout shows both halves separately."""
    if iracing_track and " — " in iracing_track:
        track_name, track_config = iracing_track.split(" — ", 1)
    else:
        track_name, track_config = (iracing_track or "—"), "—"
    return track_name, track_config


def track_image_url(iracing_track: str | None) -> str | None:
    """Existence-checked (like track_background_url below) so a track
    with a background photo but no logo yet renders as just the photo
    — no broken/missing thumbnail — rather than a stale or 404'd
    image."""
    if not iracing_track:
        return None
    track_name, _ = _split_track_name(iracing_track)
    slug = slugify_name(track_name)
    if not (TRACK_IMAGE_DIR / f"{slug}.png").is_file():
        return None
    return f"/static/img/tracks/{slug}.png"


def track_background_url(iracing_track: str | None) -> str | None:
    """Optional wide/blurred photo, layered *behind* track_image_url's
    logo on the schedule page — most tracks don't have one yet, this
    is being trialed one track at a time (currently just Zandvoort).
    Resolved by the same slug convention (<slug>-bg.jpg), so adding
    another is just dropping in a file, no code change — but unlike
    track_image_url, this one is existence-checked since the layered
    CSS only activates when a background is actually present."""
    if not iracing_track:
        return None
    track_name, _ = _split_track_name(iracing_track)
    slug = slugify_name(track_name)
    if not (TRACK_IMAGE_DIR / f"{slug}-bg.jpg").is_file():
        return None
    return f"/static/img/tracks/{slug}-bg.jpg"


def _format_race(race: dict, race_dt: datetime) -> dict:
    circuit = race["Circuit"]
    location = circuit["Location"]
    round_number = int(race["round"])
    sim_date = _thursday_before(race_dt)
    iracing_track = IRACING_TRACK_BY_ROUND.get(round_number)
    return {
        "round_number": round_number,
        "race_name": race["raceName"],
        "circuit_name": circuit["circuitName"],
        "location": f"{location['locality']}, {location['country']}",
        "race_datetime": race_dt,
        "race_date": f"{race_dt:%b} {race_dt.day}, {race_dt:%Y}",
        "race_date_iso": f"{race_dt:%Y-%m-%d}",
        "iracing_track": iracing_track,
        "track_image_url": track_image_url(iracing_track),
        "track_background_url": track_background_url(iracing_track),
        "sim_date": f"{sim_date:%b} {sim_date.day}, {sim_date:%Y}",
    }


def get_upcoming_races(season: int, *, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    races = JolpicaClient().get_full_schedule(season)

    upcoming = []
    for race in races:
        race_dt = _race_datetime(race)
        if race_dt < now:
            continue
        upcoming.append(_format_race(race, race_dt))

    upcoming.sort(key=lambda r: r["race_datetime"])
    return upcoming


def get_completed_rounds_needing_import(
    season: int, season_id: str | None, *, now: datetime | None = None
) -> list[int]:
    """Round numbers whose real-world race has already happened (by
    date/time) but that have no f1_race_results rows yet — what a
    scheduled auto-import (see discord_webhooks.check_and_import_new_f1_results)
    should pick up, without needing an admin to notice and click
    "Import F1 Results" by hand. Ascending, so a backlog (the check
    hasn't run in a while) imports oldest-first. Empty if there's no
    season yet — nothing to check against."""
    from app.services.fantasy_scoring import get_rounds_with_results

    if not season_id:
        return []

    now = now or datetime.now(timezone.utc)
    schedule = JolpicaClient().get_full_schedule(season)
    already_imported = set(get_rounds_with_results(season_id))

    needing_import = [
        int(race["round"])
        for race in schedule
        if _race_datetime(race) < now and int(race["round"]) not in already_imported
    ]
    return sorted(needing_import)


def _get_f1_session_details_by_round(season_id: str, *, is_sprint: bool) -> dict[int, dict]:
    """Real per-round Formula 1 results, keyed by round_number — shared
    by get_f1_session_details_by_round (race) and
    get_f1_sprint_session_details_by_round (sprint shootout, only
    exists for rounds with a sprint weekend). Same "missing key means
    no real import yet" contract as get_sim_session_details_by_round.
    `interval` is Jolpica's winner-total-time-or-gap string, None
    (rendered as "DNF") for anything not classified with a time.
    `fantasy_points` is the league's own scoring
    (fantasy_scoring.points_for_position against the season's active
    scale, same scale for race and sprint) for that finish position —
    not f1_race_results.points, which is real-world F1 points and isn't
    shown here — None if scoring rules haven't been seeded yet."""
    client = admin_client()
    rows = (
        client.table("f1_race_results")
        .select(
            "round_number, finish_position, start_position, car_number, status, "
            "interval, laps, fastest_lap, fastest_lap_time, fastest_lap_number, "
            "f1_drivers(full_name, team_name)"
        )
        .eq("season_id", season_id)
        .eq("is_sprint", is_sprint)
        .order("round_number")
        .order("finish_position")
        .execute()
        .data
    )
    if not rows:
        return {}

    try:
        points_table, _ = get_active_points_table(season_id)
    except ScoringRulesNotSeededError:
        points_table = {}
    if is_sprint and points_table:
        points_table = sprint_points_table(points_table)

    detail_by_round: dict[int, dict] = defaultdict(lambda: {"results": []})
    for row in rows:
        driver = row["f1_drivers"]
        team_name = driver["team_name"]
        detail_by_round[row["round_number"]]["results"].append(
            {
                "position": row["finish_position"],
                "start_position": row["start_position"],
                "driver_name": driver["full_name"],
                "photo_url": driver_photo_url(driver["full_name"]),
                "car_number": row["car_number"],
                "team_name": team_name,
                "team_logo_url": logo_url_for_team(team_name) if team_name else None,
                "status": row["status"],
                "interval": row["interval"],
                "laps": row["laps"],
                "fastest_lap_time": row["fastest_lap_time"],
                "fastest_lap_number": row["fastest_lap_number"],
                "is_fastest_lap": bool(row["fastest_lap"]),
                "fantasy_points": (
                    points_for_position(row["finish_position"], points_table) if points_table else None
                ),
            }
        )
    return dict(detail_by_round)


def get_f1_session_details_by_round(season_id: str) -> dict[int, dict]:
    return _get_f1_session_details_by_round(season_id, is_sprint=False)


def get_f1_sprint_session_details_by_round(season_id: str) -> dict[int, dict]:
    """Only has an entry for rounds that actually had a sprint weekend —
    most rounds don't, so this is empty/sparse compared to the race
    results."""
    return _get_f1_session_details_by_round(season_id, is_sprint=True)


def _parse_lap_time_seconds(text: str | None) -> float | None:
    """"1:35.381" or "35.381" -> seconds, for comparing lap times.
    None (missing/unparseable) for anything else."""
    if not text:
        return None
    minutes, sep, rest = text.rpartition(":")
    try:
        seconds = float(rest)
        return seconds + int(minutes) * 60 if sep else seconds
    except ValueError:
        return None


def get_sim_session_details_by_round(season_id: str) -> dict[int, dict]:
    """Real per-round iRacing session detail (event metadata + full
    per-driver results), keyed by ff_round_number — derived entirely
    from an actual CSV import, never placeholder data. A round missing
    from this dict has no real import yet, which the schedule page uses
    to decide whether to show that round's "i" info button at all,
    rather than showing made-up data for a round nothing's actually
    been uploaded for. A handful of queries total regardless of season
    length — every non-superseded race_event this season, then every
    result row and every awarded-points row for all of them at once.
    Each result's awarded_points is the site's own Sim Racing scoring
    for that round (sim_points_awarded), not iRacing's native
    iracing_points/iracing_club_points, which are kept separately for
    reference."""
    client = admin_client()
    events = (
        client.table("race_events")
        .select("*")
        .eq("season_id", season_id)
        .eq("is_superseded", False)
        .execute()
        .data
    )
    if not events:
        return {}

    event_ids = [e["id"] for e in events]
    results = (
        client.table("race_results")
        .select(
            "race_event_id, finish_position, start_position, iracing_display_name, "
            "car_name, car_class, car_number, status, interval, laps_led, "
            "laps_completed, incidents, qualify_time, average_lap_time, "
            "fastest_lap_time, fastest_lap_number, iracing_points, "
            "iracing_club_points, old_irating, new_irating, is_ai, participant_id, "
            "participants(display_name)"
        )
        .in_("race_event_id", event_ids)
        .order("finish_position")
        .execute()
        .data
    )
    results_by_event: dict[str, list[dict]] = defaultdict(list)
    for row in results:
        results_by_event[row["race_event_id"]].append(row)

    awarded_points_rows = (
        client.table("sim_points_awarded")
        .select("race_event_id, participant_id, points")
        .in_("race_event_id", event_ids)
        .execute()
        .data
    )
    points_by_event_participant: dict[tuple[str, str], float] = {
        (row["race_event_id"], row["participant_id"]): row["points"] for row in awarded_points_rows
    }

    team_by_participant_id: dict[str, dict] = {}
    for pair in get_pairs(season_id):
        for member in pair["constructor_members"]:
            team_by_participant_id[member["participant_id"]] = {
                "team_name": pair["name"],
                "team_logo_url": pair["logo_url"],
            }

    detail_by_round: dict[int, dict] = {}
    for event in events:
        round_number = event["ff_round_number"]
        if round_number is None:
            continue

        results = [
            {
                "position": row["finish_position"],
                "start_position": row["start_position"],
                "driver_name": (
                    row["participants"]["display_name"]
                    if row["participants"]
                    else row["iracing_display_name"]
                ),
                "car": row["car_name"],
                "car_class": row["car_class"],
                "car_number": row["car_number"],
                "status": row["status"],
                "interval": row["interval"],
                "laps_led": row["laps_led"],
                "laps_completed": row["laps_completed"],
                "incidents": row["incidents"],
                "qualify_time": row["qualify_time"],
                "average_lap_time": row["average_lap_time"],
                "fastest_lap_time": row["fastest_lap_time"],
                "fastest_lap_number": row["fastest_lap_number"],
                "iracing_points": row["iracing_points"],
                "iracing_club_points": row["iracing_club_points"],
                "old_irating": row["old_irating"],
                "new_irating": row["new_irating"],
                "is_ai": row["is_ai"],
                "team_name": team_by_participant_id.get(row["participant_id"], {}).get("team_name"),
                "team_logo_url": team_by_participant_id.get(row["participant_id"], {}).get("team_logo_url"),
                "awarded_points": points_by_event_participant.get((row["race_event_id"], row["participant_id"])),
                "is_fastest_lap": False,
            }
            for row in results_by_event.get(event["id"], [])
        ]

        lap_seconds = [
            (i, _parse_lap_time_seconds(r["fastest_lap_time"]))
            for i, r in enumerate(results)
        ]
        timed = [(i, s) for i, s in lap_seconds if s is not None]
        if timed:
            fastest_index, _ = min(timed, key=lambda pair: pair[1])
            results[fastest_index]["is_fastest_lap"] = True

        detail_by_round[round_number] = {
            "track": event["track"],
            "series": event["series"],
            "start_time": event["start_time"],
            "iracing_season_year": event["iracing_season_year"],
            "iracing_season_quarter": event["iracing_season_quarter"],
            "race_week": event["race_week"],
            "strength_of_field": event["strength_of_field"],
            "special_event_type": event["special_event_type"],
            "results": results,
        }
    return detail_by_round


def _merge_schedule_with_results(
    schedule: list[dict],
    now: datetime,
    paid_track_names: set[str] = frozenset(),
    sim_session_details: dict[int, dict] | None = None,
    f1_session_details: dict[int, dict] | None = None,
    f1_sprint_session_details: dict[int, dict] | None = None,
) -> list[dict]:
    sim_session_details = sim_session_details or {}
    f1_session_details = f1_session_details or {}
    f1_sprint_session_details = f1_sprint_session_details or {}
    races = []
    next_assigned = False
    for race in schedule:
        race_dt = _race_datetime(race)
        is_past = race_dt < now
        is_next = (not is_past) and (not next_assigned)
        next_assigned = next_assigned or is_next

        formatted = _format_race(race, race_dt)
        formatted["is_past"] = is_past
        formatted["is_next"] = is_next

        track_name, _ = _split_track_name(formatted["iracing_track"])
        formatted["iracing_track_is_paid"] = track_name in paid_track_names

        formatted["sim_temperature_f"] = SIM_TEMPERATURE_BY_ROUND.get(
            formatted["round_number"], SIM_TEMPERATURE_F
        )
        formatted["sim_conditions"] = SIM_CONDITIONS_BY_ROUND.get(
            formatted["round_number"], SIM_CONDITIONS
        )
        formatted["sim_laps"] = sim_race_laps(formatted["round_number"])

        # Real per-round session detail (event + full results), not
        # placeholder data — a round has no entry here (and the schedule
        # page shows no dropdown at all for it) until an actual iRacing
        # CSV import / F1 results import exists for it.
        formatted["sim_session_detail"] = sim_session_details.get(formatted["round_number"])
        formatted["f1_session_detail"] = f1_session_details.get(formatted["round_number"])
        formatted["f1_sprint_session_detail"] = f1_sprint_session_details.get(formatted["round_number"])

        races.append(formatted)

    races.sort(key=lambda r: r["race_datetime"])
    return races


def get_season_timeline(season: int, *, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    schedule = JolpicaClient().get_full_schedule(season)

    client = public_client()
    season_row = client.table("seasons").select("id").eq("name", str(season)).execute()
    season_id = season_row.data[0]["id"] if season_row.data else None

    sim_session_details: dict[int, dict] = {}
    f1_session_details: dict[int, dict] = {}
    f1_sprint_session_details: dict[int, dict] = {}
    if season_id:
        sim_session_details = get_sim_session_details_by_round(season_id)
        f1_session_details = get_f1_session_details_by_round(season_id)
        f1_sprint_session_details = get_f1_sprint_session_details_by_round(season_id)

    paid_track_names = _get_paid_track_names()
    return _merge_schedule_with_results(
        schedule,
        now,
        paid_track_names,
        sim_session_details,
        f1_session_details,
        f1_sprint_session_details,
    )
