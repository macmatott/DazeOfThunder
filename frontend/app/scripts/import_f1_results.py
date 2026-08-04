"""
Backfill/update real-world F1 results from Jolpica-F1 into Supabase.

Run from frontend/:
    python -m app.scripts.import_f1_results 2026
    python -m app.scripts.import_f1_results 2026 --round 1
    python -m app.scripts.import_f1_results 2026 --dry-run

Safe to re-run: writes upsert on (season_id, round_number, is_sprint,
f1_driver_id).
"""

import argparse

from app.services.f1_ingest import import_season


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("season", type=int, help="F1 season year, e.g. 2026")
    parser.add_argument(
        "--round", type=int, default=None, help="Import a single round only"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and print mapped rows without writing to Supabase",
    )
    args = parser.parse_args()

    summaries = import_season(args.season, round_number=args.round, dry_run=args.dry_run)

    total_race = sum(s["race_rows"] for s in summaries)
    total_sprint = sum(s["sprint_rows"] for s in summaries)
    for s in summaries:
        if s["race_rows"] or s["sprint_rows"]:
            print(
                f"Round {s['round']}: {s['race_rows']} race rows, "
                f"{s['sprint_rows']} sprint rows"
            )
    print(f"\nTotal: {total_race} race rows, {total_sprint} sprint rows written"
          f"{' (dry-run, nothing written)' if args.dry_run else ''}")


if __name__ == "__main__":
    main()
