# Formula Fantasy — Project Context

Private F1-themed fantasy sports + iRacing league for friends (max 10
members), hosted at dazeofthunder.com ("Daze of Thunder").

## Architecture

```
Website (FastAPI + Jinja2 + HTMX, no JS framework) ──▶ Supabase (Postgres + Auth + Realtime)
        │
        └──▶ Discord (Incoming Webhooks, posted from the website's own backend)
```

- **Supabase over Firebase**: the data model is heavily relational
  (participants ↔ drafted drivers, race results ↔ standings, four
  championships computed from overlapping subsets of the same data).
  Supabase Realtime covers the live-draft requirement without giving up
  relational integrity. See `docs/architecture.md`.
- **FastAPI + Jinja2 + HTMX, not React/Next.js**: nobody on the team knows
  JS. HTMX handles live-updating pages (standings polling, tab switching)
  via server-rendered HTML fragments — hand-written JS is the exception,
  not the default, and today is limited to `schedule.js` and `draft.js`
  (page-specific behavior HTMX attributes alone can't express, e.g.
  syncing the draft intro video/audio across polls). New work should stay
  HTMX-first and reach for hand-written JS only when there's no
  declarative way to do it.
- Full schema is in `database/schema.sql`. Raw results (race_results,
  f1_race_results) are immutable — corrections supersede rather than
  mutate, so standings can always be recomputed from source data.

## Still open / unresolved

- Public vs. private page split, iRacing race format/length — see
  `docs/architecture.md` "Still open" section for the full list.

## Data source notes

- F1 real-world results: Jolpica-F1 (`api.jolpi.ca/ergast/f1`) — free,
  no auth, Ergast-schema-compatible successor to the now-defunct Ergast API.
- iRacing CSV exports: two-block format (event metadata, blank line, then
  per-driver results table). The iRacing event ID is in the **filename**
  (`eventresult_<id>_0.csv`), not the CSV body. `Cust ID` is the stable
  per-driver identifier (equals `Team ID` in solo races); display names
  are NOT unique (iRacing appends digits on collision) — always match by
  Cust ID. A real sample is at `frontend/tests/fixtures/eventresult_87601875_0.csv`.
- iRacing has paused acceptance of new API applications, so CSV
  export/import is the permanent results path here, not a placeholder
  pending a future live API connection — don't propose building live
  iRacing API integration.
- iRacing car class: **F4** (confirmed, not F3).

## Environment / credentials

Supabase project ref: `lsafzzyriftbvinrcmfa` (us-east-1). `frontend/.env`
needs `SUPABASE_URL` + both keys (anon for public reads, service_role for
admin operations) — this is gitignored, set it up locally, never commit it.

## Current status

Live in production at dazeofthunder.com (Fly.io), backed by the real
Supabase project. The 5 real league members are registered (Discord
OAuth sign-in is decoupled from league signup — an explicit "Sign Up for
the League" action creates the participant row, not just signing in).

Built and deployed: dashboard; 4-tab standings; the merged, live
turn-based Driver + Constructor Draft (pick timers, an intro video, and
per-driver easter-egg celebration audio); F1 real-world results import
from Jolpica-F1 (single round or backfill-all); iRacing CSV race-results
upload; the full point-structure scoring page; a member role hierarchy
(Owner/Admin/Daze of Thunder Member/Member) with an admin hub; and Discord
webhook automation (`app/services/discord_webhooks.py`) covering standings
posts, deploy changelogs, YouTube-live and new-F1-results notifications,
and a weekly race-week reminder — a standalone Discord bot was scaffolded
early on but was removed once webhooks turned out to cover every
requirement.
