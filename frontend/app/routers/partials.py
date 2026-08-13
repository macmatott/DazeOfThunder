"""
Endpoints that return HTML fragments for HTMX to swap in, not full pages.
This is the entire mechanism behind "live updates without writing JS" —
the draft board polls this every 2s (see draft.html's hx-trigger) and
swaps in whatever comes back.
"""

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app.services.constructor_draft import build_combined_draft_context
from app.services.draft import get_draft_countdown, get_season_id, list_active_participants
from app.services.standings import STANDINGS_TABS, TAB_EMPTY_COPY, get_standings_rows

router = APIRouter(prefix="/partials")
templates = Jinja2Templates(directory="app/templates")

DRAFT_SEASON = "2026"


@router.get("/draft-content")
def draft_content(request: Request):
    participant_id = None
    is_owner = False
    if request.state.current_user:
        participant_id = request.state.current_user["participant_id"]
        is_owner = request.state.current_user.get("is_owner", False)
    season_id = get_season_id(DRAFT_SEASON)
    context = build_combined_draft_context(season_id, participant_id)
    return templates.TemplateResponse(
        request,
        "_draft_content.html",
        {**context, "is_owner": is_owner, "participants": list_active_participants()},
    )


@router.get("/draft-countdown")
def draft_countdown(request: Request):
    season_id = get_season_id(DRAFT_SEASON)
    countdown = get_draft_countdown(season_id) if season_id else None
    return templates.TemplateResponse(request, "_draft_countdown.html", {"countdown": countdown})


@router.get("/standings-tab")
def standings_tab(request: Request, tab: str = "overall"):
    if tab not in STANDINGS_TABS:
        tab = "overall"
    season_id = get_season_id(DRAFT_SEASON)
    rows = get_standings_rows(tab, season_id)
    return templates.TemplateResponse(
        request,
        "_standings_tab.html",
        {"active_tab": tab, "rows": rows, "empty_copy": TAB_EMPTY_COPY[tab]},
    )
