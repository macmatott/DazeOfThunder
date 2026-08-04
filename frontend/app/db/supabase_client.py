"""
Two Supabase clients, deliberately kept separate:

- `public_client()` uses the anon key. Every page that isn't behind admin
  auth should read through this one — it respects RLS, so it can never
  leak data a policy doesn't explicitly allow.
- `admin_client()` uses the service_role key, which bypasses RLS entirely.
  Only ever call this from routes that have already checked the current
  user is an admin. Never pass its result (or the key) to a template.
"""

from functools import lru_cache

from supabase import Client, create_client

from app.config import settings


@lru_cache
def public_client() -> Client:
    return create_client(settings.supabase_url, settings.supabase_anon_key)


@lru_cache
def admin_client() -> Client:
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
