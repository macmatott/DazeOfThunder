from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from postgrest.exceptions import APIError

from app.services.constructor_draft import (
    DraftError,
    build_constructor_draft_context,
    launch_naming_draft,
    launch_pairing_draft,
    make_naming_pick,
    make_pairing_pick,
)
from app.services.draft import get_season_id, list_active_participants

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

CURRENT_SEASON = "2026"


@router.get("/formula-fantasy/constructor-draft")
def constructor_draft_page(request: Request):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")

    season_id = get_season_id(CURRENT_SEASON)
    participant_id = request.state.current_user["participant_id"]
    context = build_constructor_draft_context(season_id, participant_id)

    return templates.TemplateResponse(
        request,
        "constructor_draft.html",
        {
            **context,
            "is_owner": request.state.current_user.get("is_owner", False),
            "participants": list_active_participants(),
            "launch_error": None,
        },
    )


@router.post("/formula-fantasy/constructor-draft/launch-pairing")
def launch_pairing(request: Request, order: list[str] = Form(...)):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")
    if not request.state.current_user.get("is_owner"):
        return RedirectResponse("/formula-fantasy/constructor-draft")

    season_id = get_season_id(CURRENT_SEASON)
    participant_id = request.state.current_user["participant_id"]

    try:
        launch_pairing_draft(season_id, order, participant_id)
    except ValueError as exc:
        context = build_constructor_draft_context(season_id, participant_id)
        return templates.TemplateResponse(
            request,
            "constructor_draft.html",
            {
                **context,
                "is_owner": True,
                "participants": list_active_participants(),
                "launch_error": str(exc),
            },
        )

    return RedirectResponse("/formula-fantasy/constructor-draft", status_code=303)


@router.post("/formula-fantasy/constructor-draft/launch-naming")
def launch_naming(request: Request):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")
    if not request.state.current_user.get("is_owner"):
        return RedirectResponse("/formula-fantasy/constructor-draft")

    season_id = get_season_id(CURRENT_SEASON)
    participant_id = request.state.current_user["participant_id"]

    try:
        launch_naming_draft(season_id, participant_id)
    except ValueError as exc:
        context = build_constructor_draft_context(season_id, participant_id)
        return templates.TemplateResponse(
            request,
            "constructor_draft.html",
            {
                **context,
                "is_owner": True,
                "participants": list_active_participants(),
                "launch_error": str(exc),
            },
        )

    return RedirectResponse("/formula-fantasy/constructor-draft", status_code=303)


@router.post("/formula-fantasy/constructor-draft/pick-teammate")
def pick_teammate(request: Request, partner_participant_id: str = Form(...)):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")

    season_id = get_season_id(CURRENT_SEASON)
    participant_id = request.state.current_user["participant_id"]

    try:
        make_pairing_pick(season_id, participant_id, partner_participant_id)
    except (DraftError, APIError):
        # Stale click (not your turn anymore / already paired) — the
        # board re-render below reflects the real current state either way.
        pass

    context = build_constructor_draft_context(season_id, participant_id)
    return templates.TemplateResponse(
        request,
        "_constructor_draft_board.html",
        {**context, "is_owner": request.state.current_user.get("is_owner", False)},
    )


@router.post("/formula-fantasy/constructor-draft/pick-name")
def pick_name(request: Request, name: str = Form(...)):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")

    season_id = get_season_id(CURRENT_SEASON)
    participant_id = request.state.current_user["participant_id"]

    try:
        make_naming_pick(season_id, participant_id, name)
    except (DraftError, APIError):
        pass

    context = build_constructor_draft_context(season_id, participant_id)
    return templates.TemplateResponse(
        request,
        "_constructor_draft_board.html",
        {**context, "is_owner": request.state.current_user.get("is_owner", False)},
    )
