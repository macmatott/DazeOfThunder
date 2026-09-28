"""
Two Supabase clients, deliberately kept separate:

- `public_client()` uses the anon key. Every page that isn't behind admin
  auth should read through this one — it respects RLS, so it can never
  leak data a policy doesn't explicitly allow.
- `admin_client()` uses the service_role key, which bypasses RLS entirely.
  Only ever call this from routes that have already checked the current
  user is an admin. Never pass its result (or the key) to a template.

Cached per-thread rather than as one process-wide singleton (the more
obvious @lru_cache): several routes now fire off multiple independent
queries concurrently via asyncio.gather(asyncio.to_thread(...)) (see
pages.py's dashboard route) — genuinely parallel OS threads, not just
async tasks on one thread. httpx's sync Client (which supabase-py's
postgrest client uses under the hood) isn't safe for that kind of
concurrent multi-thread access to one shared instance; a real
process-wide singleton hit this directly in testing (httpx.ReadError /
WinError 10035, i.e. a socket race, when two of those concurrent calls
landed on the same connection pool at once). A thread-local cache gives
every thread — including each asyncio.to_thread worker — its own
independent client/connection pool, so concurrent callers never share
one, while calls from the *same* thread still reuse one instance same
as before.
"""

import threading

from supabase import Client, create_client

from app.config import settings

_local = threading.local()


def public_client() -> Client:
    if not hasattr(_local, "public_client"):
        _local.public_client = create_client(settings.supabase_url, settings.supabase_anon_key)
    return _local.public_client


def admin_client() -> Client:
    if not hasattr(_local, "admin_client"):
        _local.admin_client = create_client(settings.supabase_url, settings.supabase_service_role_key)
    return _local.admin_client
