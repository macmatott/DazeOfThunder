"""
F1 real-world results ingestion — Jolpica-F1 (Ergast-schema-compatible) into
f1_race_results. This is the adapter boundary named in database/schema.sql:
however results arrive, they land in f1_race_results in a consistent shape
before fantasy scoring touches them.

No separate driver-seeding step: f1_drivers rows are get-or-created here,
per result, keyed by (season_id, full_name) with team_name taken from that
same result's Constructor — sidesteps needing to model reserve drivers
separately, since only drivers who actually appear in results get created.

Writes use admin_client() (service_role) — this runs as an offline script,
not an authenticated user request.
"""

from __future__ import annotations

import time

import httpx
from supabase import Client

from app.config import settings
from app.db.supabase_client import admin_client

# Jolpica/Ergast still labels these two constructors under older/shorter
# names than their current official branding (confirmed live: the API's
# `Constructor.name` for constructorId "red_bull"/"rb" is still "Red Bull"/
# "RB F1 Team") — normalized here at driver-creation time so
# f1_drivers.team_name, and everything keyed off it (constructor logos,
# easter-egg celebration sounds), uses the corrected name instead of
# propagating the API's stale one.
CONSTRUCTOR_NAME_ALIASES = {
    "Red Bull": "Red Bull Racing",
    "RB F1 Team": "Racing Bulls",
}


def normalize_constructor_name(name: str) -> str:
    return CONSTRUCTOR_NAME_ALIASES.get(name, name)


class JolpicaClient:
    def __init__(self, base_url: str | None = None, request_delay: float = 1.0):
        self._base_url = (base_url or settings.f1_data_api_base_url).rstrip("/")
        self._delay = request_delay
        self._http = httpx.Client(timeout=10.0)

    def _get(self, path: str, *, retries: int = 3) -> dict:
        for attempt in range(retries + 1):
            resp = self._http.get(f"{self._base_url}{path}")
            if resp.status_code == 429 and attempt < retries:
                retry_after = float(resp.headers.get("Retry-After", 5))
                time.sleep(retry_after)
                continue
            resp.raise_for_status()
            break
        time.sleep(self._delay)
        return resp.json()

    def get_schedule(self, season: int) -> list[int]:
        """Round numbers on the season's calendar, in order."""
        data = self._get(f"/{season}.json")
        races = data["MRData"]["RaceTable"]["Races"]
        return [int(r["round"]) for r in races]

    def get_full_schedule(self, season: int) -> list[dict]:
        """Full race entries (round, raceName, Circuit, date, time)."""
        data = self._get(f"/{season}.json")
        return data["MRData"]["RaceTable"]["Races"]

    def get_race_results(self, season: int, round_number: int) -> dict | None:
        """Race name + Results list, or None if the race hasn't happened yet."""
        data = self._get(f"/{season}/{round_number}/results.json")
        races = data["MRData"]["RaceTable"]["Races"]
        if not races:
            return None
        race = races[0]
        return {"race_name": race["raceName"], "results": race["Results"]}

    def get_sprint_results(self, season: int, round_number: int) -> dict | None:
        """Race name + SprintResults list, or None if no sprint that round."""
        data = self._get(f"/{season}/{round_number}/sprint.json")
        races = data["MRData"]["RaceTable"]["Races"]
        if not races:
            return None
        race = races[0]
        return {"race_name": race["raceName"], "results": race["SprintResults"]}

    def get_driver_standings(self, season: int) -> list[dict]:
        """Final championship standings for a completed season."""
        data = self._get(f"/{season}/driverStandings.json")
        lists = data["MRData"]["StandingsTable"]["StandingsLists"]
        return lists[0]["DriverStandings"] if lists else []


def map_result_to_row(
    result: dict,
    *,
    season_id: str,
    round_number: int,
    race_name: str,
    is_sprint: bool,
    f1_driver_id: str,
) -> dict:
    """One Jolpica Results/SprintResults entry -> one f1_race_results row.

    Time/FastestLap are absent for non-classified results (e.g. a DNF),
    so both are read defensively rather than assumed present."""
    fastest_lap_info = result.get("FastestLap", {})
    fastest_lap = fastest_lap_info.get("rank") == "1"
    return {
        "season_id": season_id,
        "round_number": round_number,
        "race_name": race_name,
        "is_sprint": is_sprint,
        "f1_driver_id": f1_driver_id,
        "finish_position": int(result["position"]),
        "status": result["status"],
        "points": float(result["points"]),
        "fastest_lap": fastest_lap,
        "car_number": int(result["number"]) if result.get("number") else None,
        "start_position": int(result["grid"]) if result.get("grid") else None,
        "interval": result.get("Time", {}).get("time"),
        "laps": int(result["laps"]) if result.get("laps") else None,
        "fastest_lap_time": fastest_lap_info.get("Time", {}).get("time"),
        "fastest_lap_number": int(fastest_lap_info["lap"]) if fastest_lap_info.get("lap") else None,
    }


def get_or_create_season(client: Client, name: str, *, dry_run: bool = False) -> str:
    existing = client.table("seasons").select("id").eq("name", name).execute()
    if existing.data:
        return existing.data[0]["id"]
    if dry_run:
        return f"<would-create-season:{name}>"
    created = client.table("seasons").insert({"name": name}).execute()
    return created.data[0]["id"]


def get_or_create_driver(
    client: Client,
    season_id: str,
    *,
    given_name: str,
    family_name: str,
    team_name: str,
    cache: dict[str, str],
    dry_run: bool = False,
    driver_number: int | None = None,
) -> str:
    full_name = f"{given_name} {family_name}"
    if full_name in cache:
        return cache[full_name]

    existing = (
        client.table("f1_drivers")
        .select("id, driver_number")
        .eq("season_id", season_id)
        .eq("full_name", full_name)
        .execute()
    )
    if existing.data:
        driver_id = existing.data[0]["id"]
        # Self-healing backfill: driver_number was added after this driver
        # row may have already been created by an earlier import — fill it
        # in from whatever result we're looking at now instead of needing
        # a one-off migration script.
        if not dry_run and driver_number and not existing.data[0]["driver_number"]:
            client.table("f1_drivers").update({"driver_number": driver_number}).eq(
                "id", driver_id
            ).execute()
    elif dry_run:
        driver_id = f"<would-create-driver:{full_name}>"
    else:
        created = (
            client.table("f1_drivers")
            .insert(
                {
                    "season_id": season_id,
                    "full_name": full_name,
                    "team_name": team_name,
                    "driver_number": driver_number,
                }
            )
            .execute()
        )
        driver_id = created.data[0]["id"]

    cache[full_name] = driver_id
    return driver_id


def _import_results(
    client: Client,
    jolpica_results: list[dict],
    *,
    season_id: str,
    round_number: int,
    race_name: str,
    is_sprint: bool,
    driver_cache: dict[str, str],
    dry_run: bool,
) -> int:
    rows = []
    for result in jolpica_results:
        driver = result["Driver"]
        driver_id = get_or_create_driver(
            client,
            season_id,
            given_name=driver["givenName"],
            family_name=driver["familyName"],
            team_name=normalize_constructor_name(result["Constructor"]["name"]),
            cache=driver_cache,
            dry_run=dry_run,
            driver_number=int(driver["permanentNumber"]) if driver.get("permanentNumber") else None,
        )
        rows.append(
            map_result_to_row(
                result,
                season_id=season_id,
                round_number=round_number,
                race_name=race_name,
                is_sprint=is_sprint,
                f1_driver_id=driver_id,
            )
        )

    if dry_run:
        for row in rows:
            print(f"    [dry-run] {row}")
        return len(rows)

    if rows:
        client.table("f1_race_results").upsert(
            rows, on_conflict="season_id,round_number,is_sprint,f1_driver_id"
        ).execute()
    return len(rows)


def import_round(
    jolpica: JolpicaClient,
    client: Client,
    *,
    season_id: str,
    season_year: int,
    round_number: int,
    driver_cache: dict[str, str],
    dry_run: bool = False,
) -> dict:
    """Imports race results, and sprint results if the round had one."""
    race_count = 0
    sprint_count = 0

    race = jolpica.get_race_results(season_year, round_number)
    if race is not None:
        race_count = _import_results(
            client,
            race["results"],
            season_id=season_id,
            round_number=round_number,
            race_name=race["race_name"],
            is_sprint=False,
            driver_cache=driver_cache,
            dry_run=dry_run,
        )

    sprint = jolpica.get_sprint_results(season_year, round_number)
    if sprint is not None:
        sprint_count = _import_results(
            client,
            sprint["results"],
            season_id=season_id,
            round_number=round_number,
            race_name=sprint["race_name"],
            is_sprint=True,
            driver_cache=driver_cache,
            dry_run=dry_run,
        )

    return {"round": round_number, "race_rows": race_count, "sprint_rows": sprint_count}


def import_season(
    season_year: int,
    *,
    round_number: int | None = None,
    dry_run: bool = False,
) -> list[dict]:
    client = admin_client()
    jolpica = JolpicaClient()
    season_id = get_or_create_season(client, str(season_year), dry_run=dry_run)
    driver_cache: dict[str, str] = {}

    rounds = [round_number] if round_number else jolpica.get_schedule(season_year)

    summaries = []
    for rnd in rounds:
        summary = import_round(
            jolpica,
            client,
            season_id=season_id,
            season_year=season_year,
            round_number=rnd,
            driver_cache=driver_cache,
            dry_run=dry_run,
        )
        summaries.append(summary)
    return summaries
