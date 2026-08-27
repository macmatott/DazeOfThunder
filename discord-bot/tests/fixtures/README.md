# Test Fixtures

Real (or realistic, anonymized) iRacing exports live here. These are
the ground truth the results parser is tested against — per the
project context doc, the parser should be built and tested against an
actual export, not an assumed format.

The site's race-results ingestion (weekly race imports and Team Event
results) runs on iRacing's **JSON** "event result" export now, not the
older CSV export — the JSON carries everything the CSV did plus real
Strength of Field for Hosted-session races, real qualifying results,
and the event id in the body instead of only the filename.

JSON fixtures:
- `eventresult-88113080.json` — a real **Hosted session** (this
  league's actual weekly race format), solo drivers, no official-series
  season/week metadata of its own.
- `eventresult-87103907.json` — a real official series (24 Hours of
  Spa), single-class, and a **team race**: each result entry is keyed
  by `team_id` (one per car) with a nested `driver_results` list, one
  entry per co-driver, rather than a flat per-driver row like a solo
  race.
- `eventresult-87448524.json` — another real official series team
  race, and **multiclass** (GTP/Dallara P217/IMSA23) — exercises Team
  Events' own per-class ranking against something genuinely multiclass.

The older CSV fixtures (`eventresult_87601875_0.csv`,
`eventresult_88113080_0.csv`) are kept only as a historical record of
the format the site used to ingest — nothing in the app parses CSV
exports anymore.

`.gitignore` excludes `*.csv` and `*.json` everywhere except this
`tests/fixtures` directory, so fixtures are the one place these exports
are safe to commit.
