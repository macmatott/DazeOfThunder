from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from postgrest.exceptions import APIError

from app.services.constructor_draft import get_pairs
from app.services.draft import (
    CONSTRUCTOR_LOGOS,
    get_draft_picks,
    get_ranked_drivers,
    get_season_id,
    logo_url_for_team,
)
from app.services.f1_schedule import get_season_timeline, get_upcoming_races
from app.services.fantasy_scoring import (
    MultipleActiveScoringRuleVersionsError,
    ScoringRulesNotSeededError,
    get_active_points_table,
    sprint_points_table,
)
from app.services.participants import (
    get_participant,
    parse_iracing_cust_id,
    update_participant,
)
from app.services.standings import (
    STANDINGS_TABS,
    TAB_EMPTY_COPY,
    get_constructor_standings,
    get_fantasy_only_standings,
    get_formula_fantasy_standings,
    get_sim_only_standings,
    get_standings_rows,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

CURRENT_SEASON = 2026


@router.get("/")
def dashboard(request: Request):
    season_id = get_season_id(str(CURRENT_SEASON))
    overall_standings = get_formula_fantasy_standings(season_id)
    fantasy_standings = get_fantasy_only_standings(season_id)
    sim_standings = get_sim_only_standings(season_id)
    constructor_standings = get_constructor_standings(season_id)
    upcoming_races = get_upcoming_races(CURRENT_SEASON)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "overall_leader": overall_standings[0] if overall_standings else None,
            "fantasy_leader": fantasy_standings[0] if fantasy_standings else None,
            "sim_racing_leader": sim_standings[0] if sim_standings else None,
            "constructor_leader": constructor_standings[0] if constructor_standings else None,
            "next_race": upcoming_races[0] if upcoming_races else None,
        },
    )


@router.get("/formula-fantasy")
def formula_fantasy_landing(request: Request):
    # The nav's Formula Fantasy box is a dropdown-only trigger now, but old
    # links/bookmarks to the bare URL should still land somewhere real.
    return RedirectResponse("/formula-fantasy/how-it-works")


@router.get("/formula-fantasy/how-it-works")
def formula_fantasy_how_it_works(request: Request):
    return templates.TemplateResponse(request, "ff_how_it_works.html", {})


@router.get("/formula-fantasy/schedule")
def ff_schedule(request: Request):
    races = get_season_timeline(CURRENT_SEASON)
    return templates.TemplateResponse(request, "ff_schedule.html", {"races": races})


@router.get("/formula-fantasy/draft-recap")
def ff_draft_recap(request: Request):
    season_id = get_season_id(str(CURRENT_SEASON))
    picks = get_draft_picks(season_id) if season_id else []
    teams = get_pairs(season_id) if season_id else []
    return templates.TemplateResponse(
        request, "ff_draft_recap.html", {"picks": picks, "teams": teams}
    )


def _points_table_or_empty(season_id: str | None, rule_type: str) -> list[tuple[int, float]]:
    if not season_id:
        return []
    try:
        table, _ = get_active_points_table(season_id, rule_type=rule_type)
    except (ScoringRulesNotSeededError, MultipleActiveScoringRuleVersionsError):
        return []
    return sorted(table.items())


@router.get("/formula-fantasy/mock-draft")
def ff_mock_draft(request: Request):
    season_id = get_season_id(str(CURRENT_SEASON))
    drivers = get_ranked_drivers(season_id) if season_id else []
    constructors = [
        {"name": name, "logo_url": logo_url_for_team(name)} for name in sorted(CONSTRUCTOR_LOGOS)
    ]
    return templates.TemplateResponse(
        request,
        "ff_mock_draft.html",
        {"drivers": drivers, "constructors": constructors},
    )


@router.get("/formula-fantasy/scoring")
def ff_scoring(request: Request):
    season_id = get_season_id(str(CURRENT_SEASON))
    fantasy_points = _points_table_or_empty(season_id, "fantasy_f1")
    return templates.TemplateResponse(
        request,
        "ff_scoring.html",
        {
            "fantasy_points": fantasy_points,
            "sprint_points": sorted(sprint_points_table(dict(fantasy_points)).items()) if fantasy_points else [],
            "sim_points": _points_table_or_empty(season_id, "sim_racing"),
        },
    )


@router.get("/formula-fantasy/standings")
def ff_standings(request: Request, tab: str = "overall"):
    if tab not in STANDINGS_TABS:
        tab = "overall"
    season_id = get_season_id(str(CURRENT_SEASON))
    rows = get_standings_rows(tab, season_id)
    return templates.TemplateResponse(
        request,
        "ff_standings.html",
        {"active_tab": tab, "rows": rows, "empty_copy": TAB_EMPTY_COPY[tab]},
    )


@router.get("/profile")
def profile_page(request: Request):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")
    if not request.state.current_user.get("participant_id"):
        return RedirectResponse("/")
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
    if not request.state.current_user.get("participant_id"):
        return RedirectResponse("/")

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
