# Formula Fantasy

A private F1-themed fantasy sports + iRacing league platform for friends.
Hosted at **dazeofthunder.com**.

Combines:
1. A real-world F1 fantasy driver draft (11 members, 2 drivers each)
2. An iRacing sim racing league following the F1 calendar
3. Four championships: Formula Fantasy (combined), Sim Racing, Fantasy, Constructors
4. A website (central source of truth) + a read-only Discord bot

## Architecture

```
Website (frontend) ──┐
                      ├──▶ Supabase (Postgres + Auth + Realtime)
Discord Bot (Python) ─┘
```

See `docs/architecture.md` for the full reasoning, including why Supabase
was chosen over Firebase and what's still undecided.

## Repository structure

```
frontend/       Website (framework TBD)
discord-bot/     Python bot — reads Supabase, posts to Discord. No scoring logic.
database/        schema.sql + migrations — Supabase/Postgres source of truth
docs/            architecture.md and other design docs
```

## Status

Early scaffolding. Supabase project + dazeofthunder.com domain registration
in progress. See `/areas/formula-fantasy.md`-equivalent tracking for the
current list of open decisions (constructor pairing, frontend framework,
draft order mechanism, scoring weights).

## Setup

1. Create a Supabase project, apply `database/schema.sql`.
2. Copy `.env.example` to `.env` and fill in Supabase + Discord credentials.
3. `cd discord-bot && pip install -r requirements.txt && python -m bot.main`
   (frontend setup TBD once a framework is chosen)
