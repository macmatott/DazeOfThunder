"""
Seed the NASCAR-style fantasy scoring rules for a season.

Run from frontend/:
    python -m app.scripts.seed_scoring_rules 2026
    python -m app.scripts.seed_scoring_rules 2026 --grid-size 22
    python -m app.scripts.seed_scoring_rules 2026 --dry-run

Safe to re-run: upserts on (season_id, rule_type, version, position), then
deactivates any other version for that (season, rule_type).
"""

import argparse

from app.services.draft import get_season_id
from app.services.fantasy_scoring import (
    DEFAULT_GRID_SIZE,
    DEFAULT_RULE_TYPE,
    DEFAULT_WIN_BONUS,
    NASCAR_RULE_VERSION,
    seed_scoring_rules,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("season", type=str, help="Season name, e.g. 2026")
    parser.add_argument("--rule-type", default=DEFAULT_RULE_TYPE)
    parser.add_argument("--version", default=NASCAR_RULE_VERSION)
    parser.add_argument("--grid-size", type=int, default=DEFAULT_GRID_SIZE)
    parser.add_argument("--win-bonus", type=int, default=DEFAULT_WIN_BONUS)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the rows that would be written without writing them",
    )
    args = parser.parse_args()

    season_id = get_season_id(args.season)
    if not season_id:
        print(f"No season named {args.season!r} found — run import_f1_results first.")
        return

    rows = seed_scoring_rules(
        season_id,
        version=args.version,
        grid_size=args.grid_size,
        win_bonus=args.win_bonus,
        rule_type=args.rule_type,
        dry_run=args.dry_run,
    )

    for row in rows:
        print(f"  position {row['position']}: {row['points']} pts")
    print(
        f"\n{len(rows)} rows for version {args.version!r}"
        f"{' (dry-run, nothing written)' if args.dry_run else ' written'}"
    )


if __name__ == "__main__":
    main()
