"""
Threads sign-in state to every page as `request.state.current_user`
(a dict or None) without touching each route handler — every template
already receives `request` via `templates.TemplateResponse(request, ...)`,
so `base.html`'s nav reads `request.state.current_user` directly.

Must run after Starlette's SessionMiddleware (registered in app/main.py),
since it reads `request.session`.
"""

import time

from starlette.middleware.base import BaseHTTPMiddleware


AUTH_SESSION_KEYS = (
    "access_token",
    "refresh_token",
    "expires_at",
    "participant_id",
    "is_admin",
    "display_name",
    "avatar_url",
)


class CurrentUserMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        session = request.session
        expires_at = session.get("expires_at")

        if expires_at and expires_at > time.time():
            request.state.current_user = {
                "participant_id": session.get("participant_id"),
                "is_admin": session.get("is_admin", False),
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
