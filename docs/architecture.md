# Architecture

## Current direction (supersedes the original Discord-bot-only MVP)

```
Website (FastAPI + Jinja2 + HTMX) ──▶ Supabase (Postgres + Auth + Realtime + Storage)
        │
        └──▶ Discord (Incoming Webhooks, posted from the website's own backend)
```

Supabase is the single source of truth. The website reads/writes through it
(direct client queries under RLS, or service_role for admin operations —
e.g. CSV import, scoring recalculation). Discord posting is a set of
Incoming Webhooks called directly from the website's backend
(`app/services/discord_webhooks.py`) — standings updates, results imports,
deploy changelogs, and scheduled reminders (via secret-gated `/internal/*`
routes triggered by GitHub Actions crons, since Fly.io's machine
auto-stops when idle). A standalone read-only Discord bot was scaffolded
early on but was dropped once the webhook-based approach turned out to
cover every requirement without a second always-running process to host.

## Why Supabase over Firebase

The data model is heavily relational: participants ↔ drafted drivers
(many-to-many via draft picks), race events ↔ race results, four
championships computed from overlapping subsets of the same underlying
results, constructors joining two-or-more participants' results together.
Firestore (document-based) would require denormalizing this or simulating
joins in application code. Supabase Realtime (Postgres row-change
streaming) covers the live-draft real-time requirement that was the main
argument for Firebase, without giving up relational integrity.

## Known open structural question

**Constructors' Championship pairing.** League size is capped at 11, which
doesn't split evenly into 2-person teams. `constructor_members` is modeled
as a join table (not a fixed 2-column pairing) so this isn't blocking at
the schema level, but the actual pairing rule (cap league at 10/12, allow
one team of 3, one member sits out) is still undecided — see
/areas/formula-fantasy.md.

## F1 driver pool sizing

For the 2026 season specifically, the F1 grid expanded to 11 teams / 22
full-time drivers (Cadillac's debut), which happens to match 11 members ×
2 drivers exactly. Do not treat that as a permanent invariant — the
`f1_drivers` table and draft logic should validate pool size vs. picks
needed at draft time rather than assuming they always match.

## F1 real-world data source

Ergast (the long-standing free F1 API most hobby projects used) shut down
at the end of 2024. Jolpica-F1 (`api.jolpi.ca/ergast/f1`) is the
community-maintained, Ergast-schema-compatible successor — free, no auth,
actively covering the current season. Recommended as the adapter target
for `f1_race_results` ingestion, behind a thin adapter layer so the source
can be swapped later without touching the fantasy scoring engine.

## Still open (see /areas/formula-fantasy.md and the original design doc)

- Public vs. private page split
- iRacing race format, race length
