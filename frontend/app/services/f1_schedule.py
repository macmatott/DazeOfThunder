"""
F1 schedule data for the Formula Fantasy section. `get_upcoming_races`
fetches the season calendar live from Jolpica-F1 and filters to what's
still ahead (used by the landing page). `get_season_timeline` additionally
merges in real results from `f1_race_results` (used by the full-season
Schedule page) — reads go through `public_client()`, since this is
public-facing data.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.db.supabase_client import public_client
from app.services.driver_photos import slugify_name
from app.services.f1_ingest import JolpicaClient

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
    13: 72,
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


def _group_results_by_round(rows: list[dict]) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = {}
    for row in rows:
        driver = row["f1_drivers"]
        grouped.setdefault(row["round_number"], []).append(
            {
                "position": row["finish_position"],
                "driver_name": driver["full_name"],
                "team_name": driver["team_name"],
                "points": row["points"],
                "status": row["status"],
            }
        )
    return grouped


def _session_detail(
    *,
    round_number: int,
    race_name: str,
    iracing_track: str | None,
    location: str,
    sim_date: str,
    sim_temperature_f: int,
    sim_conditions: str,
    is_past: bool,
    results: list[dict] | None,
) -> dict:
    """
    Fields for the session detail popout. This project has no iRacing API
    connection, so most of this is static placeholder data (same value on
    every race, never implying it's live) — only track/venue/round/date/
    weather/results-derived fields are real. "—" marks fields we don't
    track at all (session/subsession/DB IDs, timestamps, etc.).
    """
    track_name, track_config = _split_track_name(iracing_track)

    f1_laps = F1_LAPS_BY_ROUND.get(round_number)
    sim_laps = sim_race_laps(round_number)
    if sim_laps:
        race_length = f"{sim_laps} laps"
        race_laps_detail = f"{sim_laps} laps (50% of {f1_laps})"
    else:
        race_length = "50% GP"
        race_laps_detail = "—"

    return {
        "track": {
            "name": track_name,
            "config": track_config,
            "track_id": "—",
            "venue": location,
        },
        "session_meta": {
            "session_id": "—",
            "subsession_id": "—",
            "status": "Completed" if is_past else "Scheduled",
            "launch_at": f"{sim_date}, 9:00 PM EST",
            "has_results": "Yes" if results else "No",
            "password_protected": "No",
            "driver_changes": "No",
            "lone_qualify": "No",
        },
        "session_lengths": {
            "practice": "8:30 PM",
            "qualifying": "10 minutes",
            "race": race_length,
            "qualify_laps": "N/A",
            "race_laps": race_laps_detail,
            "total_time_limit": "—",
        },
        "entries": {
            "entered": 0,
            "team_entries": 0,
            "max_drivers": 24,
            "race_number": round_number,
        },
        "weather": {
            "temperature_f": sim_temperature_f,
            "skies": "Clear",
            "humidity": "45%",
            "wind": "N @ 2 km/h",
            "precip_option": sim_conditions,
            "fog": "0%",
            "allow_fog": "No",
            "var_initial": "0",
            "var_ongoing": "0",
        },
        "track_state": {
            "leave_marbles": "Yes",
            "practice_rubber": "Carry-over",
            "qualify_rubber": "Carry-over",
            "race_rubber": "Carry-over",
        },
        "database": {
            "db_id": "—",
            "race_name": race_name,
            "description": "—",
            "series_type": "—",
            "race_number": round_number,
            "race_date_db": sim_date,
            "signup_deadline": "—",
            "auto_signup": "No",
            "signup_msg_id": "—",
            "selected_track_id": "—",
            "selected_car_ids": "—",
            "created_at": "—",
            "updated_at": "—",
        },
    }


def _merge_schedule_with_results(
    schedule: list[dict],
    results_by_round: dict[int, list[dict]],
    now: datetime,
    paid_track_names: set[str] = frozenset(),
) -> list[dict]:
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
        formatted["results"] = (
            results_by_round.get(formatted["round_number"], []) if is_past else None
        )

        track_name, _ = _split_track_name(formatted["iracing_track"])
        formatted["iracing_track_is_paid"] = track_name in paid_track_names

        formatted["sim_temperature_f"] = SIM_TEMPERATURE_BY_ROUND.get(
            formatted["round_number"], SIM_TEMPERATURE_F
        )
        formatted["sim_conditions"] = SIM_CONDITIONS_BY_ROUND.get(
            formatted["round_number"], SIM_CONDITIONS
        )
        formatted["sim_laps"] = sim_race_laps(formatted["round_number"])

        formatted["session_detail"] = _session_detail(
            round_number=formatted["round_number"],
            race_name=formatted["race_name"],
            iracing_track=formatted["iracing_track"],
            location=formatted["location"],
            sim_date=formatted["sim_date"],
            sim_temperature_f=formatted["sim_temperature_f"],
            sim_conditions=formatted["sim_conditions"],
            is_past=is_past,
            results=formatted["results"],
        )

        races.append(formatted)

    races.sort(key=lambda r: r["race_datetime"])
    return races


def get_season_timeline(season: int, *, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    schedule = JolpicaClient().get_full_schedule(season)

    client = public_client()
    season_row = client.table("seasons").select("id").eq("name", str(season)).execute()

    results_by_round: dict[int, list[dict]] = {}
    if season_row.data:
        season_id = season_row.data[0]["id"]
        rows = (
            client.table("f1_race_results")
            .select("round_number, finish_position, points, status, f1_drivers(full_name, team_name)")
            .eq("season_id", season_id)
            .eq("is_sprint", False)
            .order("round_number")
            .order("finish_position")
            .execute()
        ).data
        results_by_round = _group_results_by_round(rows)

    paid_track_names = _get_paid_track_names()
    return _merge_schedule_with_results(schedule, results_by_round, now, paid_track_names)
