"""
Threads sign-in state to every page as `request.state.current_user`
(a dict or None) without touching each route handler — every template
already receives `request` via `templates.TemplateResponse(request, ...)`,
so `base.html`'s nav reads `request.state.current_user` directly.

Must run after Starlette's SessionMiddleware (registered in app/main.py),
since it reads `request.session`.
"""

import asyncio
import time

from starlette.middleware.base import BaseHTTPMiddleware

from app.services.auth import refresh_session


AUTH_SESSION_KEYS = (
    "access_token",
    "refresh_token",
    "expires_at",
    "auth_user_id",
    "participant_id",
    "role",
    "is_active",
    "display_name",
    "avatar_url",
)

# Refresh a little before the access token actually expires so a request
# that lands right at the boundary doesn't race it.
REFRESH_LEEWAY_SECONDS = 60


class CurrentUserMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        session = request.session
        expires_at = session.get("expires_at")

        # The Supabase access token itself only lives ~1hr — without this,
        # anyone idle (or asleep) longer than that gets silently signed out
        # and has to redo Discord OAuth. Swap it for a fresh one via the
        # long-lived refresh_token instead of treating this as a real logout.
        if expires_at and session.get("refresh_token") and expires_at <= time.time() + REFRESH_LEEWAY_SECONDS:
            try:
                refreshed = await asyncio.to_thread(refresh_session, session["refresh_token"])
            except Exception:
                refreshed = None
            if refreshed:
                session["access_token"] = refreshed.access_token
                session["refresh_token"] = refreshed.refresh_token
                session["expires_at"] = refreshed.expires_at
                expires_at = refreshed.expires_at

        if expires_at and expires_at > time.time():
            role = session.get("role", "member")
            request.state.current_user = {
                "participant_id": session.get("participant_id"),
                "role": role,
                "is_admin": role in ("owner", "admin"),
                "is_owner": role == "owner",
                "is_active": session.get("is_active", False),
                "display_name": session.get("display_name"),
                "avatar_url": session.get("avatar_url"),
            }
        else:
            request.state.current_user = None
            # Only clear a *stale* auth session (expires_at was set, but has
            # passed) — never touch the rest of the session, since it may be
            # mid-login (oauth_verifier, set by /auth/login and read by
            # /auth/callback moments later on the very next request).
            if expires_at:
                for key in AUTH_SESSION_KEYS:
                    session.pop(key, None)

        return await call_next(request)
