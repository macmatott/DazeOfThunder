from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app.services.f1_schedule import get_upcoming_races
from app.services.standings import get_formula_fantasy_standings

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

CURRENT_SEASON = 2026


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


@router.get("/formula-fantasy")
def formula_fantasy_landing(request: Request):
    races = get_upcoming_races(CURRENT_SEASON)
    return templates.TemplateResponse(
        request, "formula_fantasy.html", {"races": races}
    )


@router.get("/formula-fantasy/standings/combined")
def ff_standings_combined(request: Request):
    standings = get_formula_fantasy_standings()
    return templates.TemplateResponse(
        request, "standings.html", {"standings": standings}
    )


@router.get("/formula-fantasy/standings/sim-racing")
def ff_standings_sim_racing(request: Request):
    return templates.TemplateResponse(
        request, "ff_standings_stub.html", {"trophy_name": "Sim Racing"}
    )


@router.get("/formula-fantasy/standings/fantasy")
def ff_standings_fantasy(request: Request):
    return templates.TemplateResponse(
        request, "ff_standings_stub.html", {"trophy_name": "Fantasy"}
    )


@router.get("/formula-fantasy/standings/constructors")
def ff_standings_constructors(request: Request):
    return templates.TemplateResponse(
        request, "ff_standings_stub.html", {"trophy_name": "Constructors"}
    )


@router.get("/schedule")
def schedule_page(request: Request):
    return templates.TemplateResponse(request, "schedule.html", {})


@router.get("/draft")
def draft_page(request: Request):
    return templates.TemplateResponse(request, "draft.html", {})
