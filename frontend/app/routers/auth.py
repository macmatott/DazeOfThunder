from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.services.auth import build_authorize_url, derive_display_name, exchange_code
from app.services.participants import get_or_create_participant

router = APIRouter(prefix="/auth")


@router.get("/login")
def login(request: Request):
    redirect_to = str(request.url_for("auth_callback"))
    url, verifier = build_authorize_url(redirect_to)
    request.session["oauth_verifier"] = verifier
    return RedirectResponse(url)


@router.get("/callback", name="auth_callback")
def callback(request: Request, code: str | None = None):
    verifier = request.session.pop("oauth_verifier", None)
    if not code or not verifier:
        return RedirectResponse("/")

    session = exchange_code(code, verifier)

    participant = get_or_create_participant(
        session.user.id, derive_display_name(session.user.user_metadata)
    )

    request.session["access_token"] = session.access_token
    request.session["refresh_token"] = session.refresh_token
    request.session["expires_at"] = session.expires_at
    request.session["participant_id"] = participant["id"]
    request.session["display_name"] = participant["display_name"]
    request.session["avatar_url"] = session.user.user_metadata.get("avatar_url")

    return RedirectResponse("/")


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
