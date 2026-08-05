"""
Fantasy F1 scoring — our own points scale, not real F1 points.
`f1_race_results.points` (real F1 points) is reference data only; league
scoring runs on a NASCAR-style scale instead, scaled to the actual grid
size rather than borrowing NASCAR's raw 40-car numbers: 1st place scores
`grid_size` points, 2nd gets a win bonus taken off that, then every
position after drops by 1, floored at 1 point so every classified
finisher scores (for a 22-car grid: 1st=22, 2nd=20, 3rd=19, ... 22nd=1).
DNFs still score — `finish_position` is always the classified position
regardless of `status`, same as real NASCAR (a car that drops out still
scores based on where it was running).

The position -> points mapping lives in `scoring_rules` (versioned, so
historical `fantasy_points_awarded` rows stay reproducible even after the
scale changes) rather than being hardcoded — `seed_scoring_rules` writes
it, `get_active_points_table` reads it back. A round's fantasy score is
the sum across all of a participant's drafted drivers' results that
round — race and sprint both count, same table for each.
"""

from __future__ import annotations

from collections import defaultdict

from app.db.supabase_client import admin_client

NASCAR_RULE_VERSION = "nascar-v2-scaled"
DEFAULT_RULE_TYPE = "fantasy_f1"
DEFAULT_GRID_SIZE = 22
DEFAULT_WIN_BONUS = 2


def nascar_points_table(
    grid_size: int = DEFAULT_GRID_SIZE, win_bonus: int = DEFAULT_WIN_BONUS
) -> dict[int, float]:
    """1st = grid_size; 2nd = grid_size - win_bonus; every position after
    that drops by 1, floored at 1 point (every classified finisher scores,
    same NASCAR-inspired shape as before but proportional to the actual
    grid size instead of NASCAR's own ~40-car numbers)."""
    table = {1: float(grid_size)}
    second_place = grid_size - win_bonus
    for position in range(2, grid_size + 1):
        table[position] = max(1.0, float(second_place - (position - 2)))
    return table


class ScoringRulesNotSeededError(Exception):
    pass


class MultipleActiveScoringRuleVersionsError(Exception):
    pass


def build_scoring_rule_rows(
    season_id: str,
    *,
    rule_type: str = DEFAULT_RULE_TYPE,
    version: str = NASCAR_RULE_VERSION,
    grid_size: int = DEFAULT_GRID_SIZE,
) -> list[dict]:
    """One row per position, shaped for a `scoring_rules` insert/upsert."""
    return [
        {
            "season_id": season_id,
            "rule_type": rule_type,
            "version": version,
            "position": position,
            "points": points,
            "is_active": True,
        }
        for position, points in nascar_points_table(grid_size).items()
    ]


def points_for_position(position: int | None, points_table: dict[int, float]) -> float:
    if position is None:
        return 0.0
    return points_table.get(position, 0.0)


def group_results_by_driver(round_results: list[dict]) -> dict[str, list[dict]]:
    """f1_race_results rows for one round -> {f1_driver_id: [row, ...]}
    (normally 1 row, 2 if that round had a sprint)."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in round_results:
        grouped[row["f1_driver_id"]].append(row)
    return grouped


def score_driver_results(results: list[dict], points_table: dict[int, float]) -> float:
    """Sum of points across all of one driver's result rows for the round
    (race + sprint both use points_table — no separate sprint scale)."""
    return sum(points_for_position(r.get("finish_position"), points_table) for r in results)


def score_participant_round(
    drafted_driver_ids: list[str],
    results_by_driver: dict[str, list[dict]],
    points_table: dict[int, float],
) -> float:
    """Sum across however many of the participant's drafted drivers raced
    that round — drivers with no result that round contribute 0."""
    total = 0.0
    for driver_id in drafted_driver_ids:
        total += score_driver_results(results_by_driver.get(driver_id, []), points_table)
    return total


def compute_round_scores(
    draft_picks: list[dict],
    round_results: list[dict],
    points_table: dict[int, float],
) -> dict[str, float]:
    """{participant_id: total_points}. Participants with zero draft picks
    are simply absent — nothing to score."""
    drivers_by_participant: dict[str, list[str]] = defaultdict(list)
    for pick in draft_picks:
        drivers_by_participant[pick["participant_id"]].append(pick["f1_driver_id"])

    results_by_driver = group_results_by_driver(round_results)

    return {
        participant_id: score_participant_round(driver_ids, results_by_driver, points_table)
        for participant_id, driver_ids in drivers_by_participant.items()
    }


def compute_driver_season_stats(
    season_results: list[dict], points_table: dict[int, float]
) -> dict[str, dict]:
    """{f1_driver_id: {"total": ..., "average": ...}} across every result
    row for a season (all rounds, race + sprint) — same grouping/summing
    as a single round's scoring, just fed a whole season's results at
    once. `average` is per race *weekend* (distinct round_number), not per
    result row — a sprint weekend contributes 2 rows but is still one
    week. Used to show "what would this driver have scored under our
    scale", independent of who (if anyone) actually drafted them."""
    grouped = group_results_by_driver(season_results)
    stats = {}
    for driver_id, rows in grouped.items():
        total = score_driver_results(rows, points_table)
        weeks = len({r["round_number"] for r in rows}) or 1
        stats[driver_id] = {"total": total, "average": total / weeks}
    return stats


def _points_table_from_rule_rows(rows: list[dict]) -> tuple[dict[int, float], str]:
    if not rows:
        raise ScoringRulesNotSeededError("No active fantasy_f1 scoring rules for this season.")
    versions = {row["version"] for row in rows}
    if len(versions) > 1:
        raise MultipleActiveScoringRuleVersionsError(
            f"Multiple active scoring rule versions found: {sorted(versions)}"
        )
    table = {row["position"]: float(row["points"]) for row in rows}
    return table, versions.pop()


def seed_scoring_rules(
    season_id: str,
    *,
    version: str = NASCAR_RULE_VERSION,
    grid_size: int = DEFAULT_GRID_SIZE,
    rule_type: str = DEFAULT_RULE_TYPE,
    dry_run: bool = False,
) -> list[dict]:
    """Upserts the position->points table for `version`, deletes any rows
    beyond `grid_size` left over from a previous seed of this *same*
    version with a larger grid (upsert alone never removes rows outside
    what it's given), then deactivates every other version for this
    (season, rule_type) so exactly one is ever active. Re-running with the
    same version and grid_size is a safe no-op; a rules change is a new
    version string + an explicit re-run of score_fantasy_points — past
    fantasy_points_awarded rows keep whatever scoring_rule_version they
    were calculated under, untouched here."""
    rows = build_scoring_rule_rows(
        season_id, rule_type=rule_type, version=version, grid_size=grid_size
    )
    if dry_run:
        return rows

    client = admin_client()
    client.table("scoring_rules").upsert(
        rows, on_conflict="season_id,rule_type,version,position"
    ).execute()
    client.table("scoring_rules").delete().eq("season_id", season_id).eq(
        "rule_type", rule_type
    ).eq("version", version).gt("position", grid_size).execute()
    client.table("scoring_rules").update({"is_active": False}).eq(
        "season_id", season_id
    ).eq("rule_type", rule_type).neq("version", version).execute()
    return rows


def get_active_points_table(
    season_id: str, *, rule_type: str = DEFAULT_RULE_TYPE
) -> tuple[dict[int, float], str]:
    client = admin_client()
    rows = (
        client.table("scoring_rules")
        .select("position, points, version")
        .eq("season_id", season_id)
        .eq("rule_type", rule_type)
        .eq("is_active", True)
        .execute()
        .data
    )
    return _points_table_from_rule_rows(rows)


def get_round_results(season_id: str, round_number: int) -> list[dict]:
    client = admin_client()
    return (
        client.table("f1_race_results")
        .select("f1_driver_id, finish_position, is_sprint")
        .eq("season_id", season_id)
        .eq("round_number", round_number)
        .execute()
        .data
    )


def get_rounds_with_results(season_id: str) -> list[int]:
    client = admin_client()
    rows = (
        client.table("f1_race_results")
        .select("round_number")
        .eq("season_id", season_id)
        .execute()
        .data
    )
    return sorted({row["round_number"] for row in rows})


def get_season_results(season_id: str) -> list[dict]:
    client = admin_client()
    return (
        client.table("f1_race_results")
        .select("f1_driver_id, finish_position, is_sprint, round_number")
        .eq("season_id", season_id)
        .execute()
        .data
    )


def get_driver_season_fantasy_stats_by_name(season_id: str) -> dict[str, dict]:
    """{full_name: {"total": ..., "average": ...}} for a season, keyed by
    name (not id) so callers matching against a *different* season's
    f1_drivers rows (e.g. a later season's draft pool) can look drivers up
    the same way draft.py used to for real F1 points."""
    client = admin_client()
    drivers = (
        client.table("f1_drivers")
        .select("id, full_name")
        .eq("season_id", season_id)
        .execute()
        .data
    )
    names_by_id = {d["id"]: d["full_name"] for d in drivers}

    points_table, _ = get_active_points_table(season_id)
    stats_by_driver_id = compute_driver_season_stats(get_season_results(season_id), points_table)

    return {
        names_by_id[driver_id]: stats
        for driver_id, stats in stats_by_driver_id.items()
        if driver_id in names_by_id
    }


def score_round(season_id: str, round_number: int, *, dry_run: bool = False) -> list[dict]:
    """Scores one F1 round for every participant with a drafted driver,
    writing fantasy_points_awarded. Returns [] without writing anything if
    the round has no results yet (avoids all-zero placeholder rows)."""
    round_results = get_round_results(season_id, round_number)
    if not round_results:
        return []

    from app.services.draft import get_draft_picks  # local: draft.py imports this module too

    points_table, version = get_active_points_table(season_id)
    draft_picks = get_draft_picks(season_id)
    scores = compute_round_scores(draft_picks, round_results, points_table)

    rows = [
        {
            "season_id": season_id,
            "participant_id": participant_id,
            "round_number": round_number,
            "points": points,
            "scoring_rule_version": version,
        }
        for participant_id, points in scores.items()
    ]

    if dry_run or not rows:
        return rows

    client = admin_client()
    client.table("fantasy_points_awarded").upsert(
        rows, on_conflict="season_id,participant_id,round_number"
    ).execute()
    return rows


def score_season(
    season_id: str, *, round_number: int | None = None, dry_run: bool = False
) -> list[dict]:
    rounds = [round_number] if round_number else get_rounds_with_results(season_id)
    written = []
    for rnd in rounds:
        written.extend(score_round(season_id, rnd, dry_run=dry_run))
    return written
