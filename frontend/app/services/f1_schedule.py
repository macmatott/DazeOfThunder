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

from app.db.supabase_client import public_client
from app.services.f1_ingest import JolpicaClient

# Placeholder sim-session details shown on the Schedule page until real
# iRacing session data exists — deliberately fixed, not derived from
# anything, so they can't be mistaken for real weather/session data.
SIM_TEMPERATURE_F = 80
SIM_CONDITIONS = "No rain"

# iRacing track assigned to each round's sim race — set by league admin,
# not derived from the F1 calendar. Not tied to real-world geography (the
# sim track doesn't have to match the host country).
IRACING_TRACK_BY_ROUND: dict[int, str] = {
    1: "Phillip Island Circuit",
    2: "Okayama International Circuit -- Full Course",
    3: "Suzuka International Racing Course -- Grand Prix",
    4: "Miami International Autodrome -- Grand Prix",
    5: "Circuit Gilles Villeneuve -- Grand Prix",
    6: "Adelaide Street Circuit",
    7: "Circuit de Barcelona-Catalunya -- Grand Prix",
    8: "Red Bull Ring -- Grand Prix",
    9: "Silverstone Circuit -- Grand Prix",
    10: "Circuit de Spa-Francorchamps -- Grand Prix Pits",
    11: "Hungaroring",
    12: "Circuit Park Zandvoort",
    13: "Autodromo Nazionale Monza -- Grand Prix",
    14: "Autódromo Internacional do Algarve -- Grand Prix",
    15: "Circuit de Nevers Magny-Cours -- Grand Prix",
    16: "Nürburgring Grand-Prix-Strecke - Grand Prix",
    17: "Circuit de Lédenon -- Grand Prix",
    18: "Circuit of the Americas -- Grand Prix",
    19: "Autódromo Hermanos Rodríguez -- Grand Prix",
    20: "Autódromo José Carlos Pace -- Grand Prix",
    21: "Qualcomm Circuit (Naval Base Coronado)",
    22: "Road America -- Full Course",
    23: "Daytona International Speedway -- Road Course",
}


def _race_datetime(race: dict) -> datetime:
    date_str = race["date"]
    time = race.get("time", "00:00:00Z")
    return datetime.fromisoformat(f"{date_str}T{time}".replace("Z", "+00:00"))


def _thursday_before(race_dt: datetime) -> date:
    """Most recent Thursday on/before race_dt's date (weekday 3 = Thursday)."""
    days_since_thursday = (race_dt.weekday() - 3) % 7
    return race_dt.date() - timedelta(days=days_since_thursday)


def _format_race(race: dict, race_dt: datetime) -> dict:
    circuit = race["Circuit"]
    location = circuit["Location"]
    return {
        "round_number": int(race["round"]),
        "race_name": race["raceName"],
        "circuit_name": circuit["circuitName"],
        "location": f"{location['locality']}, {location['country']}",
        "race_datetime": race_dt,
        "race_date": f"{race_dt:%b} {race_dt.day}, {race_dt:%Y}",
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


def _merge_schedule_with_results(
    schedule: list[dict],
    results_by_round: dict[int, list[dict]],
    now: datetime,
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

        sim_date = _thursday_before(race_dt)
        formatted["sim_date"] = f"{sim_date:%b} {sim_date.day}, {sim_date:%Y}"
        formatted["sim_temperature_f"] = SIM_TEMPERATURE_F
        formatted["sim_conditions"] = SIM_CONDITIONS
        formatted["iracing_track"] = IRACING_TRACK_BY_ROUND.get(formatted["round_number"])

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

    return _merge_schedule_with_results(schedule, results_by_round, now)
