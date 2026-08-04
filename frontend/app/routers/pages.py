from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app.services.standings import get_formula_fantasy_standings

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def dashboard(request: Request):
    standings = get_formula_fantasy_standings()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "season_name": None,  # TODO: read the active season once seasons exist
            "ff_leader": standings[0]["display_name"] if standings else None,
            "constructor_leader": None,  # TODO once constructor scoring exists
            "latest_race": None,  # TODO once race_events has rows
        },
    )


@router.get("/standings")
def standings_page(request: Request):
    standings = get_formula_fantasy_standings()
    return templates.TemplateResponse(
        request, "standings.html", {"standings": standings}
    )


@router.get("/schedule")
def schedule_page(request: Request):
    return templates.TemplateResponse(request, "schedule.html", {})


@router.get("/draft")
def draft_page(request: Request):
    return templates.TemplateResponse(request, "draft.html", {})
