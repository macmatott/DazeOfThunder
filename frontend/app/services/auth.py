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
