from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.services.auth import build_authorize_url, derive_display_name, exchange_code
from app.services.participants import get_or_create_participant, get_participant_by_auth_user_id

router = APIRouter(prefix="/auth")


@router.get("/login")
def login(request: Request):
    redirect_to = str(request.url_for("auth_callback"))
    url, verifier = build_authorize_url(redirect_to)
    request.session["oauth_verifier"] = verifier
    return RedirectResponse(url)


@router.get("/callback", name="auth_callback")
def callback(
    request: Request,
    code: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    verifier = request.session.pop("oauth_verifier", None)

    if error:
        # Supabase/Discord rejected the exchange server-side (e.g. Discord
        # returned no email on the account) — surface *why* instead of a
        # silent bounce to "/" that looks like sign-in just did nothing.
        request.session["auth_error"] = (error_description or error).replace("+", " ")
        return RedirectResponse("/")

    if not code or not verifier:
        request.session["auth_error"] = (
            "Sign-in didn't complete — please try again."
        )
        return RedirectResponse("/")

    session = exchange_code(code, verifier)
    participant = get_participant_by_auth_user_id(session.user.id)

    request.session["auth_user_id"] = session.user.id
    request.session["access_token"] = session.access_token
    request.session["refresh_token"] = session.refresh_token
    request.session["expires_at"] = session.expires_at
    request.session["avatar_url"] = session.user.user_metadata.get("avatar_url")

    if participant:
        request.session["participant_id"] = participant["id"]
        request.session["role"] = participant["role"]
        request.session["is_active"] = participant["is_active"]
        request.session["display_name"] = participant["display_name"]
    else:
        # Signed in, not registered — clear any stale participant fields
        # (defensive) and source display_name from Discord directly
        # instead of a participant row, since none exists yet.
        for key in ("participant_id", "role", "is_active"):
            request.session.pop(key, None)
        request.session["display_name"] = derive_display_name(session.user.user_metadata)

    return RedirectResponse("/")


@router.post("/signup")
def signup(request: Request):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")
    if request.state.current_user.get("participant_id"):
        return RedirectResponse("/", status_code=303)  # already registered, no-op

    auth_user_id = request.session.get("auth_user_id")
    if not auth_user_id:
        return RedirectResponse("/auth/login")

    participant = get_or_create_participant(auth_user_id, request.state.current_user["display_name"])
    request.session["participant_id"] = participant["id"]
    request.session["role"] = participant["role"]
    request.session["is_active"] = participant["is_active"]
    request.session["display_name"] = participant["display_name"]

    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
