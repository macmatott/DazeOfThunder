import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Form, HTTPException, Request
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
    list_seasons_with_sim_results,
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
    participant_photo_url,
    update_participant,
)
from app.services.standings import (
    STANDINGS_TABS,
    TAB_EMPTY_COPY,
    get_constructor_standings,
    get_fantasy_only_standings,
    get_formula_fantasy_standings,
    get_participant_career_sim_stats,
    get_participant_sim_stats,
    get_sim_only_standings,
    get_standings_rows,
    get_team_career_sim_stats,
    get_team_sim_stats,
)
from app.services.team_events import list_upcoming_events

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

CURRENT_SEASON = 2026


@router.get("/")
async def dashboard(request: Request):
    season_id = get_season_id(str(CURRENT_SEASON))

    # Each of these is its own independent Supabase (or, for
    # get_upcoming_races, Jolpica) round trip, and none of them depend
    # on each other's result — sequentially, that's 6 network calls
    # back to back on every homepage load, which is exactly why it used
    # to take 6-10 seconds. Firing them concurrently instead means the
    # page waits on however long the *slowest* one takes, not the sum
    # of all six. asyncio.to_thread since these are all plain
    # synchronous calls (sync Supabase/httpx clients), same pattern
    # CurrentUserMiddleware already uses for the same reason.
    (
        overall_standings,
        fantasy_standings,
        sim_standings,
        constructor_standings,
        upcoming_races,
        upcoming_team_events,
    ) = await asyncio.gather(
        asyncio.to_thread(get_formula_fantasy_standings, season_id),
        asyncio.to_thread(get_fantasy_only_standings, season_id),
        asyncio.to_thread(get_sim_only_standings, season_id),
        asyncio.to_thread(get_constructor_standings, season_id),
        asyncio.to_thread(get_upcoming_races, CURRENT_SEASON),
        asyncio.to_thread(list_upcoming_events),
    )
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
        sim_details_by_round, f1_details_by_round = await asyncio.gather(
            asyncio.to_thread(get_sim_session_details_by_round, season_id),
            asyncio.to_thread(get_f1_session_details_by_round, season_id),
        )
        next_race_results_uploaded = next_race["round_number"] in sim_details_by_round
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
def ff_schedule(request: Request, season: int | None = None):
    seasons, selected_season = _resolve_active_season(season)
    races = get_season_timeline(int(selected_season))
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
            "seasons": seasons,
            "season": selected_season,
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


def _resolve_active_season(season: int | None) -> tuple[list[str], str]:
    """(seasons on record with sim results, the one to actually show) —
    shared by the schedule and results routes so their season dropdowns/
    fallback behavior can't drift apart. Keyed off sim results (not just
    a seasons table row) so a season that only exists for mock-draft
    reference data (2025) never shows up as a real, selectable season."""
    seasons = list_seasons_with_sim_results()
    if season and str(season) in seasons:
        return seasons, str(season)
    if str(CURRENT_SEASON) in seasons:
        return seasons, str(CURRENT_SEASON)
    return seasons, (seasons[0] if seasons else str(CURRENT_SEASON))


def _completed_sim_races(season: int) -> list[dict]:
    # Our own sim race results, not F1's — only rounds with an actual
    # iRacing CSV import have a winner to show. The Grand Prix column
    # still borrows the real F1 round's flag (this is still "round N,
    # paired with the Belgian GP"), but Date is our own sim race date,
    # not the F1 date.
    races = get_season_timeline(season)
    return [r for r in races if r["sim_session_detail"] and r["sim_session_detail"]["results"]]


def _completed_f1_races(season: int) -> list[dict]:
    # The real F1 results counterpart to _completed_sim_races — only
    # rounds with an actual F1 results import have a winner to show.
    races = get_season_timeline(season)
    return [r for r in races if r["f1_session_detail"] and r["f1_session_detail"]["results"]]


def _resolve_results_type(type: str | None) -> str:
    return type if type in ("league", "f1") else "league"


def _races_for_type(results_type: str, season: int) -> list[dict]:
    return _completed_sim_races(season) if results_type == "league" else _completed_f1_races(season)


@router.get("/formula-fantasy/results")
def ff_results(request: Request, season: int | None = None, type: str = "league"):
    results_type = _resolve_results_type(type)
    seasons, selected_season = _resolve_active_season(season)
    races = _races_for_type(results_type, int(selected_season))

    return templates.TemplateResponse(
        request,
        "ff_results.html",
        {
            "seasons": seasons,
            "selected_season": selected_season,
            "races": races,
            "gp_races": races,
            "results_type": results_type,
        },
    )


@router.get("/formula-fantasy/results/{season}/{round_number}")
def ff_result_detail(
    request: Request, season: int, round_number: int, type: str = "league", session: str = "race"
):
    results_type = _resolve_results_type(type)
    seasons, selected_season = _resolve_active_season(season)
    races = _races_for_type(results_type, int(selected_season))
    race = next((r for r in races if r["round_number"] == round_number), None)
    if not race:
        raise HTTPException(status_code=404)

    # Sprint is F1-only and only meaningful for a round that actually had
    # one — anything else (league, or an f1 round with no sprint) always
    # falls back to the main race, regardless of what ?session= asked for.
    results_session = (
        "sprint" if session == "sprint" and results_type == "f1" and race["f1_sprint_session_detail"] else "race"
    )

    return templates.TemplateResponse(
        request,
        "ff_result_detail.html",
        {
            "race": race,
            "seasons": seasons,
            "selected_season": selected_season,
            "gp_races": races,
            "results_type": results_type,
            "results_session": results_session,
        },
    )


def _split_display_name(display_name: str) -> tuple[str, str]:
    """"Mac Matott" -> ("Mac", "Matott") for the Drivers page's two-line
    first-name/last-name card layout (modeled on the real F1 drivers
    page) — a name with no space becomes ("", the whole name), shown on
    one line instead, since there's nothing sensible to split there."""
    parts = display_name.rsplit(" ", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return "", display_name


@router.get("/formula-fantasy/drivers")
def ff_drivers(request: Request):
    season_id = get_season_id(str(CURRENT_SEASON))
    teams = get_pairs(season_id) if season_id else []
    drivers = []
    for team in teams:
        for member in team["members"]:
            first_name, last_name = _split_display_name(member["display_name"])
            drivers.append(
                {
                    "id": member["id"],
                    "first_name": first_name,
                    "last_name": last_name,
                    "car_number": member["car_number"],
                    "team_name": team["name"],
                    "team_color": team["color"],
                    "team_logo_url": team["logo_url"],
                    "photo_url": participant_photo_url(member["display_name"]),
                }
            )
    return templates.TemplateResponse(request, "ff_drivers.html", {"drivers": drivers})


@router.get("/formula-fantasy/drivers/{participant_id}")
def ff_driver_detail(request: Request, participant_id: str):
    season_id = get_season_id(str(CURRENT_SEASON))
    teams = get_pairs(season_id) if season_id else []
    driver = None
    team = None
    for t in teams:
        for member in t["members"]:
            if member["id"] == participant_id:
                driver = member
                team = t
                break
        if driver:
            break
    if not driver:
        raise HTTPException(status_code=404)

    first_name, last_name = _split_display_name(driver["display_name"])

    return templates.TemplateResponse(
        request,
        "ff_driver_detail.html",
        {
            "season": CURRENT_SEASON,
            "driver": driver,
            "first_name": first_name,
            "last_name": last_name,
            "team": team,
            "photo_url": participant_photo_url(driver["display_name"]),
            "stats": get_participant_sim_stats(participant_id, season_id),
            "career_stats": get_participant_career_sim_stats(participant_id),
        },
    )


@router.get("/formula-fantasy/teams")
def ff_teams(request: Request):
    season_id = get_season_id(str(CURRENT_SEASON))
    teams = get_pairs(season_id) if season_id else []
    for team in teams:
        for member in team["members"]:
            first_name, last_name = _split_display_name(member["display_name"])
            member["first_name"] = first_name
            member["last_name"] = last_name
            member["photo_url"] = participant_photo_url(member["display_name"])
    return templates.TemplateResponse(request, "ff_teams.html", {"season": CURRENT_SEASON, "teams": teams})


@router.get("/formula-fantasy/teams/{team_id}")
def ff_team_detail(request: Request, team_id: str):
    season_id = get_season_id(str(CURRENT_SEASON))
    teams = get_pairs(season_id) if season_id else []
    team = next((t for t in teams if t["id"] == team_id), None)
    if not team:
        raise HTTPException(status_code=404)

    for member in team["members"]:
        first_name, last_name = _split_display_name(member["display_name"])
        member["first_name"] = first_name
        member["last_name"] = last_name
        member["photo_url"] = participant_photo_url(member["display_name"])

    return templates.TemplateResponse(
        request,
        "ff_team_detail.html",
        {
            "season": CURRENT_SEASON,
            "team": team,
            "stats": get_team_sim_stats(team, season_id),
            "career_stats": get_team_career_sim_stats(team["name"]),
        },
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
