"""
Endpoints that return HTML fragments for HTMX to swap in, not full pages.
This is the entire mechanism behind "live updates without writing JS" —
the standings page polls this every 30s (see standings.html's hx-trigger)
and swaps in whatever comes back.
"""

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app.services.standings import get_formula_fantasy_standings

router = APIRouter(prefix="/partials")
templates = Jinja2Templates(directory="app/templates")


@router.get("/standings-table")
def standings_table(request: Request):
    standings = get_formula_fantasy_standings()
    return templates.TemplateResponse(
        request, "_standings_table.html", {"standings": standings}
    )
