from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from postgrest.exceptions import APIError

from app.services.draft import (
    DraftError,
    build_draft_board_context,
    get_season_id,
    launch_draft,
    list_participants,
    make_pick,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

CURRENT_SEASON = "2026"


@router.get("/formula-fantasy/draft")
def draft_page(request: Request):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")

    season_id = get_season_id(CURRENT_SEASON)
    participant_id = request.state.current_user["participant_id"]
    board = build_draft_board_context(season_id, participant_id)

    return templates.TemplateResponse(
        request,
        "draft.html",
        {
            "board": board,
            "is_admin": request.state.current_user.get("is_admin", False),
            "participants": list_participants(),
            "launch_error": None,
        },
    )


@router.post("/formula-fantasy/draft/launch")
def launch(request: Request, order: list[str] = Form(...)):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")
    if not request.state.current_user.get("is_admin"):
        return RedirectResponse("/formula-fantasy/draft")

    season_id = get_season_id(CURRENT_SEASON)

    try:
        launch_draft(season_id, order, request.state.current_user["participant_id"])
    except ValueError as exc:
        board = build_draft_board_context(season_id, request.state.current_user["participant_id"])
        return templates.TemplateResponse(
            request,
            "draft.html",
            {
                "board": board,
                "is_admin": True,
                "participants": list_participants(),
                "launch_error": str(exc),
            },
        )

    return RedirectResponse("/formula-fantasy/draft", status_code=303)


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
        # board re-render below reflects the real current state either way.
        pass

    board = build_draft_board_context(season_id, participant_id)
    return templates.TemplateResponse(request, "_draft_board.html", {"board": board})
