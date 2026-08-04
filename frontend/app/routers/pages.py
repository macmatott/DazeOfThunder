from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from postgrest.exceptions import APIError

from app.services.f1_schedule import get_season_timeline, get_upcoming_races
from app.services.participants import (
    get_participant,
    parse_iracing_cust_id,
    update_participant,
)
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


@router.get("/formula-fantasy/schedule")
def ff_schedule(request: Request):
    races = get_season_timeline(CURRENT_SEASON)
    return templates.TemplateResponse(request, "ff_schedule.html", {"races": races})


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


@router.get("/profile")
def profile_page(request: Request):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")
    participant = get_participant(request.state.current_user["participant_id"])
    return templates.TemplateResponse(
        request, "profile.html", {"participant": participant, "saved": False, "error": None}
    )


@router.post("/profile")
def profile_update(
    request: Request,
    display_name: str = Form(...),
    iracing_display_name: str = Form(""),
    iracing_cust_id: str = Form(""),
):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")

    participant_id = request.state.current_user["participant_id"]
    display_name = display_name.strip()
    error = None

    try:
        cust_id = parse_iracing_cust_id(iracing_cust_id)
    except ValueError:
        error = "iRacing Customer ID must be a number."
        participant = get_participant(participant_id)
        return templates.TemplateResponse(
            request, "profile.html", {"participant": participant, "saved": False, "error": error}
        )

    try:
        participant = update_participant(
            participant_id,
            display_name=display_name,
            iracing_display_name=iracing_display_name.strip() or None,
            iracing_cust_id=cust_id,
        )
    except APIError as exc:
        if exc.code == "23505":
            error = "That iRacing Customer ID is already linked to another profile."
        else:
            error = "Couldn't save your profile — please try again."
        participant = get_participant(participant_id)
        return templates.TemplateResponse(
            request, "profile.html", {"participant": participant, "saved": False, "error": error}
        )

    # Update both: the session cookie (for future requests) and
    # request.state.current_user (already set by CurrentUserMiddleware
    # before this handler ran, so the nav in *this* response needs it too).
    request.session["display_name"] = participant["display_name"]
    request.state.current_user["display_name"] = participant["display_name"]
    return templates.TemplateResponse(
        request, "profile.html", {"participant": participant, "saved": True, "error": None}
    )
