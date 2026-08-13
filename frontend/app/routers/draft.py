from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from postgrest.exceptions import APIError

from app.services.constructor_draft import (
    DraftError as ConstructorDraftError,
    build_combined_draft_context,
    launch_naming_draft,
    launch_pairing_draft,
    make_naming_pick,
    make_pairing_pick,
)
from app.services.draft import (
    DraftError,
    get_season_id,
    list_active_participants,
    make_pick,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

CURRENT_SEASON = "2026"


def _build_page_context(request: Request, *, launch_error: str | None = None) -> dict:
    season_id = get_season_id(CURRENT_SEASON)
    participant_id = request.state.current_user["participant_id"]
    return {
        **build_combined_draft_context(season_id, participant_id),  # board, phase, pairing, naming
        "is_owner": request.state.current_user.get("is_owner", False),
        "participants": list_active_participants(),
        "launch_error": launch_error,
    }


@router.get("/formula-fantasy/draft")
def draft_page(request: Request):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")

    return templates.TemplateResponse(request, "draft.html", _build_page_context(request))


@router.get("/formula-fantasy/constructor-draft")
def constructor_draft_redirect():
    # Retired as a standalone page — the Constructor Draft is now the
    # second half of the combined /formula-fantasy/draft flow.
    return RedirectResponse("/formula-fantasy/draft", status_code=301)


@router.post("/formula-fantasy/draft/pick")
def pick(request: Request, f1_driver_id: str = Form(...)):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")

    season_id = get_season_id(CURRENT_SEASON)
    participant_id = request.state.current_user["participant_id"]

    try:
        make_pick(season_id, participant_id, f1_driver_id)
    except (DraftError, APIError):
        # Stale click (not your turn anymore / driver just taken) — the
        # re-render below reflects the real current state either way.
        pass

    # Renders the full combined content (not just the driver board) so a
    # pick that happens to complete the Driver Draft immediately reveals
    # the Constructor Draft section too, not just on the next 2s poll.
    return templates.TemplateResponse(request, "_draft_content.html", _build_page_context(request))


@router.post("/formula-fantasy/draft/launch-pairing")
def launch_pairing(request: Request, order: list[str] = Form(...)):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")
    if not request.state.current_user.get("is_owner"):
        return RedirectResponse("/formula-fantasy/draft")

    season_id = get_season_id(CURRENT_SEASON)
    participant_id = request.state.current_user["participant_id"]

    try:
        launch_pairing_draft(season_id, order, participant_id)
    except ValueError as exc:
        return templates.TemplateResponse(
            request, "draft.html", _build_page_context(request, launch_error=str(exc))
        )

    return RedirectResponse("/formula-fantasy/draft", status_code=303)


@router.post("/formula-fantasy/draft/launch-naming")
def launch_naming(request: Request):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")
    if not request.state.current_user.get("is_owner"):
        return RedirectResponse("/formula-fantasy/draft")

    season_id = get_season_id(CURRENT_SEASON)
    participant_id = request.state.current_user["participant_id"]

    try:
        launch_naming_draft(season_id, participant_id)
    except ValueError as exc:
        return templates.TemplateResponse(
            request, "draft.html", _build_page_context(request, launch_error=str(exc))
        )

    return RedirectResponse("/formula-fantasy/draft", status_code=303)


@router.post("/formula-fantasy/draft/pick-teammate")
def pick_teammate(request: Request, partner_participant_id: str = Form(...)):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")

    season_id = get_season_id(CURRENT_SEASON)
    participant_id = request.state.current_user["participant_id"]

    try:
        make_pairing_pick(season_id, participant_id, partner_participant_id)
    except (ConstructorDraftError, APIError):
        pass

    return templates.TemplateResponse(request, "_draft_content.html", _build_page_context(request))


@router.post("/formula-fantasy/draft/pick-name")
def pick_name(request: Request, name: str = Form(...)):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")

    season_id = get_season_id(CURRENT_SEASON)
    participant_id = request.state.current_user["participant_id"]

    try:
        make_naming_pick(season_id, participant_id, name)
    except (ConstructorDraftError, APIError):
        pass

    return templates.TemplateResponse(request, "_draft_content.html", _build_page_context(request))
