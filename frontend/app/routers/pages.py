from datetime import datetime, timezone

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from postgrest.exceptions import APIError

from app.services.constructor_draft import get_pairs
from app.services.draft import (
    CONSTRUCTOR_LOGOS,
    LEAGUE_TIMEZONE,
    compute_draft_countdown,
    get_draft_picks,
    get_ranked_drivers,
    get_season_id,
    logo_url_for_team,
)
from app.services.f1_schedule import (
    get_f1_session_details_by_round,
    get_season_timeline,
    get_sim_session_details_by_round,
    get_upcoming_races,
)
from app.services.fantasy_scoring import (
    MultipleActiveScoringRuleVersionsError,
    ScoringRulesNotSeededError,
    get_active_points_table,
    sprint_points_table,
)
from app.services.participants import (
    get_participant,
    parse_car_number,
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
from app.services.team_events import list_upcoming_events

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
    upcoming_team_events = list_upcoming_events()
    next_race = upcoming_races[0] if upcoming_races else None
    next_team_event = upcoming_team_events[0] if upcoming_team_events else None

    now = datetime.now(timezone.utc)
    next_race_countdown = compute_draft_countdown(next_race["sim_datetime"], now) if next_race else None
    # Once next_race's sim race has actually happened, the countdown
    # clamps to 0 same as any other expired countdown — but "Starting
    # any moment" reads wrong at that point if we already have real
    # results for it (round's done, not about to start), so the card
    # swaps in "Sim Race Complete" instead. See stat_card_countdown's
    # soon_label param.
    next_race_results_uploaded = False
    next_f1_race_results_uploaded = False
    if next_race and season_id:
        sim_details_by_round = get_sim_session_details_by_round(season_id)
        next_race_results_uploaded = next_race["round_number"] in sim_details_by_round
        f1_details_by_round = get_f1_session_details_by_round(season_id)
        next_f1_race_results_uploaded = next_race["round_number"] in f1_details_by_round

    # The real F1 race — separate from the sim race above (same round,
    # different day: the sim race runs the Thursday before). Jolpica
    # gives every round a real start time, past and future, so this is
    # actual data, not an assumed one like the team event's 6 PM.
    # Converted to the league's own Eastern timezone (same as the sim
    # race and team event targets) rather than left in Jolpica's raw
    # UTC — the countdown math itself doesn't change (a duration is the
    # same regardless of which timezone the two ends are expressed in),
    # but this keeps all three targets consistently Eastern-anchored.
    next_f1_countdown = None
    next_f1_countdown_target = None
    if next_race:
        f1_race_datetime_et = next_race["race_datetime"].astimezone(LEAGUE_TIMEZONE)
        next_f1_countdown = compute_draft_countdown(f1_race_datetime_et, now)
        next_f1_countdown_target = f1_race_datetime_et.isoformat()

    # list_upcoming_events already attaches countdown/countdown_target to
    # every event (see team_events.py::event_countdown_target) — the
    # same 6 PM ET convention the /schedule page's own next-event card
    # uses, computed in one place instead of each caller picking its own
    # assumed start hour.
    next_team_event_countdown = next_team_event["countdown"] if next_team_event else None
    next_team_event_countdown_target = next_team_event["countdown_target"] if next_team_event else None

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "overall_leader": overall_standings[0] if overall_standings else None,
            "fantasy_leader": fantasy_standings[0] if fantasy_standings else None,
            "sim_racing_leader": sim_standings[0] if sim_standings else None,
            "constructor_leader": constructor_standings[0] if constructor_standings else None,
            "next_race": next_race,
            "next_race_countdown": next_race_countdown,
            "next_race_results_uploaded": next_race_results_uploaded,
            "next_f1_countdown": next_f1_countdown,
            "next_f1_countdown_target": next_f1_countdown_target,
            "next_f1_race_results_uploaded": next_f1_race_results_uploaded,
            "next_team_event": next_team_event,
            "next_team_event_countdown": next_team_event_countdown,
            "next_team_event_countdown_target": next_team_event_countdown_target,
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
    next_sim_race = next((r for r in races if r["is_next_sim_race"]), None)
    now = datetime.now(timezone.utc)
    sim_countdown = compute_draft_countdown(next_sim_race["sim_datetime"], now) if next_sim_race else None

    # Same sim-race/real-F1-race pairing as the dashboard's Next League
    # Race card, in one banner instead of two separate ones (see
    # race_countdown_banner's countdown2 param). get_season_timeline
    # already attaches sim_session_detail/f1_session_detail to every
    # race, so "is this round actually done" reuses that instead of a
    # separate query the way the dashboard route needs to.
    f1_countdown = None
    f1_countdown_target = None
    if next_sim_race:
        f1_race_datetime_et = next_sim_race["race_datetime"].astimezone(LEAGUE_TIMEZONE)
        f1_countdown = compute_draft_countdown(f1_race_datetime_et, now)
        f1_countdown_target = f1_race_datetime_et.isoformat()
    sim_race_complete = bool(next_sim_race and next_sim_race.get("sim_session_detail"))
    f1_race_complete = bool(next_sim_race and next_sim_race.get("f1_session_detail"))

    return templates.TemplateResponse(
        request,
        "ff_schedule.html",
        {
            "races": races,
            "next_sim_race": next_sim_race,
            "sim_countdown": sim_countdown,
            "f1_countdown": f1_countdown,
            "f1_countdown_target": f1_countdown_target,
            "sim_race_complete": sim_race_complete,
            "f1_race_complete": f1_race_complete,
        },
    )


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
    rows, progression = get_standings_rows(tab, season_id)
    return templates.TemplateResponse(
        request,
        "ff_standings.html",
        {"active_tab": tab, "rows": rows, "progression": progression, "empty_copy": TAB_EMPTY_COPY[tab]},
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
    car_number: str = Form(""),
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
        number = parse_car_number(car_number)
    except ValueError:
        error = "Car Number must be a number."
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
            car_number=number,
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
