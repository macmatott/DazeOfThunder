# Database

Supabase-hosted Postgres. `schema.sql` is the current source-of-truth DDL —
apply it via the Supabase SQL editor, or via the Supabase CLI once that's
set up:

```bash
supabase db push
```

`migrations/` will hold versioned migrations once the Supabase CLI is
initialized (`supabase init`) — for now `schema.sql` is applied directly
since the schema is still taking shape pre-launch.

See `../docs/architecture.md` for the reasoning behind key schema decisions
(constructor pairing as a join table, points tables kept separate from raw
results, etc).
