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
it, `get_active_points_table` reads it back.

Sprint results are worth much less than a full race in real F1 (roughly
a third), so they score on their own derived scale rather than the race
scale directly — see sprint_points_table(). It isn't seeded/versioned
separately: it's always computed from whichever race scale is currently
active, the same way the race scale itself is only ever "whatever's
active right now" at scoring time. A round's fantasy score is the sum
across all of a participant's drafted drivers' results that round, each
row scored on its own scale (race or sprint) by `is_sprint`.
"""

from __future__ import annotations

import math
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
    win_bonus: int = DEFAULT_WIN_BONUS,
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
        for position, points in nascar_points_table(grid_size, win_bonus).items()
    ]


def points_for_position(position: int | None, points_table: dict[int, float]) -> float:
    if position is None:
        return 0.0
    return points_table.get(position, 0.0)


def round_half_up(value: float) -> int:
    """Standard round-to-nearest, ties rounding up (unlike Python's
    built-in round(), which rounds ties to even)."""
    return math.floor(value + 0.5)


def sprint_points_table(race_points_table: dict[int, float]) -> dict[int, float]:
    """Sprint scoring is the race scale thirded (round_half_up), floored
    at 1 for every position that scored at all in the race scale — real
    F1 pays sprints roughly a third of a full race (8 vs 25 for the
    win), and this keeps our own "every classified finisher scores"
    rule intact rather than zeroing out anyone below the real F1
    sprint's top 8. Thirding then flooring can otherwise tie 1st and
    2nd (e.g. 22 and 20 both third-and-round to 7), so the winner is
    bumped to one more point than 2nd — same idea as the race scale's
    own win_bonus, just reapplied at this reduced tier."""
    table = {position: max(1.0, float(round_half_up(points / 3))) for position, points in race_points_table.items()}
    if 1 in table and 2 in table:
        table[1] = table[2] + 1
    return table


def group_results_by_driver(round_results: list[dict]) -> dict[str, list[dict]]:
    """f1_race_results rows for one round -> {f1_driver_id: [row, ...]}
    (normally 1 row, 2 if that round had a sprint)."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in round_results:
        grouped[row["f1_driver_id"]].append(row)
    return grouped


def score_driver_results(
    results: list[dict], race_points_table: dict[int, float], sprint_table: dict[int, float]
) -> float:
    """Sum of points across all of one driver's result rows for the
    round — each row scored against the race or sprint scale by its own
    `is_sprint` flag."""
    total = 0.0
    for r in results:
        table = sprint_table if r.get("is_sprint") else race_points_table
        total += points_for_position(r.get("finish_position"), table)
    return total


def score_participant_round(
    drafted_driver_ids: list[str],
    results_by_driver: dict[str, list[dict]],
    race_points_table: dict[int, float],
    sprint_table: dict[int, float],
) -> float:
    """Sum across however many of the participant's drafted drivers raced
    that round — drivers with no result that round contribute 0."""
    total = 0.0
    for driver_id in drafted_driver_ids:
        total += score_driver_results(results_by_driver.get(driver_id, []), race_points_table, sprint_table)
    return total


def compute_round_scores(
    draft_picks: list[dict],
    round_results: list[dict],
    race_points_table: dict[int, float],
    sprint_table: dict[int, float],
) -> dict[str, float]:
    """{participant_id: total_points}. Participants with zero draft picks
    are simply absent — nothing to score."""
    drivers_by_participant: dict[str, list[str]] = defaultdict(list)
    for pick in draft_picks:
        drivers_by_participant[pick["participant_id"]].append(pick["f1_driver_id"])

    results_by_driver = group_results_by_driver(round_results)

    return {
        participant_id: score_participant_round(driver_ids, results_by_driver, race_points_table, sprint_table)
        for participant_id, driver_ids in drivers_by_participant.items()
    }


def compute_driver_season_stats(
    season_results: list[dict], race_points_table: dict[int, float], sprint_table: dict[int, float]
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
        total = score_driver_results(rows, race_points_table, sprint_table)
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
    win_bonus: int = DEFAULT_WIN_BONUS,
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
        season_id, rule_type=rule_type, version=version, grid_size=grid_size, win_bonus=win_bonus
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

    race_table, _ = get_active_points_table(season_id)
    stats_by_driver_id = compute_driver_season_stats(
        get_season_results(season_id), race_table, sprint_points_table(race_table)
    )

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

    race_table, version = get_active_points_table(season_id)
    draft_picks = get_draft_picks(season_id)
    scores = compute_round_scores(draft_picks, round_results, race_table, sprint_points_table(race_table))

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


def get_fantasy_breakdown_by_participant(
    season_id: str,
) -> tuple[dict[str, list[dict]], list[int], set[int]]:
    """Per-driver, per-race-round points for every participant's own
    drafted drivers — feeds the Fantasy Championship standings page's
    per-member dropdown (drivers as rows, race rounds as columns).
    Recomputed live from the same source data as score_round/score_season
    rather than reading fantasy_points_awarded, so it reflects the
    active points table even if a round hasn't been (re-)scored yet.

    Returns ({participant_id: [{"driver_id", "full_name", "driver_number",
    "team_name", "logo_url", "photo_url", "points_by_round": {round_number: points},
    "positions_by_round": {round_number: [finish_position, ...]}, "total"},
    ...]}, rounds, sprint_rounds) — `rounds` is every race round with
    results this season, ascending, shared across every participant/
    driver so their rows all line up under the same columns;
    `sprint_rounds` is the subset of those that included a sprint — the
    sprint result scores on its own, lesser scale (sprint_points_table)
    but still adds into that same round's total, and the UI flags which
    rounds combined two sessions. `positions_by_round` lists the race
    finish first, then the sprint's (a sprint weekend has both), so the
    UI can show "P2/P1" alongside that round's combined points."""
    from app.services.draft import get_draft_picks  # local: draft.py imports this module too

    race_table, _ = get_active_points_table(season_id)
    sprint_table = sprint_points_table(race_table)
    rounds = get_rounds_with_results(season_id)
    season_results = get_season_results(season_id)
    sprint_rounds = {r["round_number"] for r in season_results if r.get("is_sprint")}
    results_by_driver = group_results_by_driver(season_results)
    draft_picks = get_draft_picks(season_id)

    breakdown: dict[str, list[dict]] = defaultdict(list)
    for pick in draft_picks:
        driver = pick["f1_drivers"]
        results_by_round: dict[int, list[dict]] = defaultdict(list)
        for row in results_by_driver.get(pick["f1_driver_id"], []):
            results_by_round[row["round_number"]].append(row)

        points_by_round = {
            rnd: round(score_driver_results(results_by_round.get(rnd, []), race_table, sprint_table), 1)
            for rnd in rounds
        }
        positions_by_round = {
            rnd: [
                r["finish_position"]
                for r in sorted(results_by_round.get(rnd, []), key=lambda r: bool(r.get("is_sprint")))
                if r.get("finish_position") is not None
            ]
            for rnd in rounds
        }
        breakdown[pick["participant_id"]].append(
            {
                "driver_id": pick["f1_driver_id"],
                "full_name": driver["full_name"],
                "driver_number": driver.get("driver_number"),
                "team_name": driver["team_name"],
                "logo_url": driver.get("logo_url"),
                "photo_url": driver.get("photo_url"),
                "points_by_round": points_by_round,
                "positions_by_round": positions_by_round,
                "total": round(sum(points_by_round.values()), 1),
            }
        )
    return dict(breakdown), rounds, sprint_rounds
