"""
Compute and write fantasy_points_awarded from f1_race_results + draft_picks,
using the season's active scoring_rules (see seed_scoring_rules.py).

Run from frontend/:
    python -m app.scripts.score_fantasy_points 2026
    python -m app.scripts.score_fantasy_points 2026 --round 1
    python -m app.scripts.score_fantasy_points 2026 --dry-run

Safe to re-run: writes upsert on (season_id, participant_id, round_number).
Rounds with no results yet are skipped (nothing written for them).
"""

import argparse

from app.services.draft import get_season_id
from app.services.fantasy_scoring import score_season


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("season", type=str, help="Season name, e.g. 2026")
    parser.add_argument("--round", type=int, default=None, help="Score a single round only")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and print rows without writing to Supabase",
    )
    args = parser.parse_args()

    season_id = get_season_id(args.season)
    if not season_id:
        print(f"No season named {args.season!r} found — run import_f1_results first.")
        return

    rows = score_season(season_id, round_number=args.round, dry_run=args.dry_run)

    by_round: dict[int, int] = {}
    for row in rows:
        by_round[row["round_number"]] = by_round.get(row["round_number"], 0) + 1
    for round_number, count in sorted(by_round.items()):
        print(f"Round {round_number}: {count} participant rows")

    print(
        f"\nTotal: {len(rows)} rows"
        f"{' (dry-run, nothing written)' if args.dry_run else ' written'}"
    )


if __name__ == "__main__":
    main()
