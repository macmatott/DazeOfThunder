"""
Upcoming F1 races for the Formula Fantasy landing page. Read-only — fetches
the season calendar live from Jolpica-F1 and filters to what's still ahead.
No Supabase involved; nothing here is persisted.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.services.f1_ingest import JolpicaClient


def _race_datetime(race: dict) -> datetime:
    date = race["date"]
    time = race.get("time", "00:00:00Z")
    return datetime.fromisoformat(f"{date}T{time}".replace("Z", "+00:00"))


def get_upcoming_races(season: int, *, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    races = JolpicaClient().get_full_schedule(season)

    upcoming = []
    for race in races:
        race_dt = _race_datetime(race)
        if race_dt < now:
            continue
        circuit = race["Circuit"]
        location = circuit["Location"]
        upcoming.append(
            {
                "round_number": int(race["round"]),
                "race_name": race["raceName"],
                "circuit_name": circuit["circuitName"],
                "location": f"{location['locality']}, {location['country']}",
                "race_datetime": race_dt,
                "race_date": f"{race_dt:%b} {race_dt.day}, {race_dt:%Y}",
            }
        )

    upcoming.sort(key=lambda r: r["race_datetime"])
    return upcoming
