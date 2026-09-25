"""
Discord sign-in via Supabase Auth — server-side PKCE flow, no client-side
JS SDK (the site is server-rendered with an explicit no-hand-written-JS
convention; Supabase's normal browser flow expects a JS SDK to read tokens
back from a URL fragment, which doesn't fit here).

We build the /authorize URL ourselves with a PKCE code_challenge and hand
the browser a plain redirect; the ?code=... callback is exchanged for a
session entirely server-side. The code_verifier is *not* left in the
Supabase client's own storage (that client is a process-wide singleton —
see app/db/supabase_client.py — so concurrent logins would race on it);
it's passed through the caller's session cookie instead (see
app/routers/auth.py).
"""

from __future__ import annotations

import asyncio
from urllib.parse import urlencode

from supabase import create_client
from supabase_auth.helpers import generate_pkce_challenge, generate_pkce_verifier
from supabase_auth.types import Session

from app.config import settings


def derive_display_name(user_metadata: dict) -> str:
    return (
        user_metadata.get("full_name")
        or user_metadata.get("name")
        or user_metadata.get("user_name")
        or "Member"
    )


def build_authorize_url(redirect_to: str) -> tuple[str, str]:
    verifier = generate_pkce_verifier()
    challenge = generate_pkce_challenge(verifier)
    params = {
        "provider": "discord",
        "redirect_to": redirect_to,
        "code_challenge": challenge,
        "code_challenge_method": "s256",
    }
    url = f"{settings.supabase_url}/auth/v1/authorize?{urlencode(params)}"
    return url, verifier


def exchange_code(code: str, code_verifier: str) -> Session:
    # A fresh, throwaway client — not the cached public_client() singleton.
    # exchange_code_for_session() saves the resulting session onto the
    # client's own internal storage; reusing the shared singleton would
    # leak this user's session into every other visitor's anonymous reads.
    client = create_client(settings.supabase_url, settings.supabase_anon_key)
    response = client.auth.exchange_code_for_session(
        {"auth_code": code, "code_verifier": code_verifier}
    )
    return response.session


def refresh_session(refresh_token: str) -> Session:
    # Supabase access tokens are short-lived (~1hr) — CurrentUserMiddleware
    # calls this to silently renew one via its long-lived refresh_token
    # instead of signing the user out every time the access token expires.
    client = create_client(settings.supabase_url, settings.supabase_anon_key)
    response = client.auth.refresh_session(refresh_token)
    return response.session


# In-process only (single Fly machine, no cross-process coordination
# needed) — see refresh_session_deduped.
_pending_refreshes: dict[str, asyncio.Task] = {}


async def refresh_session_deduped(refresh_token: str) -> Session | None:
    """Wraps refresh_session so concurrent callers holding the *same*
    refresh_token share one underlying call instead of racing it.

    Supabase invalidates a refresh_token the instant it's used and
    issues a new one — so two nearly-simultaneous requests (e.g. the
    header's 60s poll landing alongside an ordinary page load, right as
    the ~1hr access token is due to expire) would otherwise both try to
    redeem it: one succeeds, the other fails with an "already used"
    error. CurrentUserMiddleware used to treat that failure exactly
    like a genuinely dead token and wipe the whole session, signing the
    user out — a real, reproducible bug caused by request timing, not
    actual token expiry.

    The first caller for a given refresh_token starts the real refresh
    and every other caller racing it just awaits that same in-flight
    task, so they all resolve to the one successful (or one failed)
    result together instead of stepping on each other. A failure still
    surfaces as None here, same as the old try/except-around-the-call
    did for its single caller."""

    async def _do_refresh() -> Session | None:
        try:
            return await asyncio.to_thread(refresh_session, refresh_token)
        except Exception:
            return None

    task = _pending_refreshes.get(refresh_token)
    if task is None:
        task = asyncio.ensure_future(_do_refresh())
        _pending_refreshes[refresh_token] = task
        task.add_done_callback(lambda _t: _pending_refreshes.pop(refresh_token, None))
    return await task
