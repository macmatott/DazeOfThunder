"""
Endpoints that return HTML fragments for HTMX to swap in, not full pages.
This is the entire mechanism behind "live updates without writing JS" —
the draft board polls this every 2s (see draft.html's hx-trigger) and
swaps in whatever comes back.
"""

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app.services.constructor_draft import build_constructor_draft_context
from app.services.draft import build_draft_board_context, get_season_id

router = APIRouter(prefix="/partials")
templates = Jinja2Templates(directory="app/templates")

DRAFT_SEASON = "2026"


@router.get("/draft-board")
def draft_board(request: Request):
    participant_id = None
    if request.state.current_user:
        participant_id = request.state.current_user["participant_id"]
    season_id = get_season_id(DRAFT_SEASON)
    board = build_draft_board_context(season_id, participant_id)
    return templates.TemplateResponse(request, "_draft_board.html", {"board": board})


@router.get("/constructor-draft-board")
def constructor_draft_board(request: Request):
    participant_id = None
    is_admin = False
    if request.state.current_user:
        participant_id = request.state.current_user["participant_id"]
        is_admin = request.state.current_user.get("is_admin", False)
    season_id = get_season_id(DRAFT_SEASON)
    context = build_constructor_draft_context(season_id, participant_id)
    return templates.TemplateResponse(
        request, "_constructor_draft_board.html", {**context, "is_admin": is_admin}
    )
