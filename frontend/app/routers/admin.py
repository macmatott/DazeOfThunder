import httpx
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services.constructor_draft import get_constructor_draft_summary
from app.services.discord_webhooks import notify_fantasy_round, notify_sim_round
from app.services.draft import (
    format_draft_scheduled_at_local,
    get_driver_draft_summary,
    get_season,
    get_season_id,
    list_active_participants,
    parse_draft_scheduled_at,
    save_draft_order,
    set_draft_scheduled_at,
)
from app.services.f1_ingest import import_season
from app.services.f1_schedule import get_season_timeline
from app.services.fantasy_scoring import (
    MultipleActiveScoringRuleVersionsError,
    ScoringRulesNotSeededError,
)
from app.services.iracing_ingest import (
    DuplicateEventError,
    JsonParseError,
    RoundAlreadyImportedError,
    import_race_json,
    list_recent_race_events,
)
from app.services.standings import (
    get_constructor_standings,
    get_formula_fantasy_standings,
    get_sim_only_standings,
)
from app.services.participants import (
    ROLE_DOT_MEMBER,
    ROLE_MEMBER,
    ROLE_OWNER,
    approve_participant,
    get_participant,
    list_all_participants,
    list_pending_participants,
    set_participant_role,
)
from app.services.team_event_results import get_team_event_results, import_team_event_results
from app.services.team_events import (
    InvalidEventDateRangeError,
    InvalidImageError,
    create_team_event,
    delete_team_event,
    get_team_event,
    list_all_events,
    parse_car_classes,
    update_team_event,
    upload_event_image,
)

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="app/templates")

CURRENT_SEASON = "2026"

ADMIN_TABS = ("site", "league", "team-events")
DEFAULT_ADMIN_TAB = "site"


def _build_hub_context(request: Request, active_tab: str = DEFAULT_ADMIN_TAB) -> dict:
    season_id = get_season_id(CURRENT_SEASON)
    season = get_season(season_id) if season_id else None
    scheduled_at = season.get("draft_scheduled_at") if season else None
    return {
        "active_tab": active_tab,
        "season_name": CURRENT_SEASON if season_id else None,
        "driver_draft": get_driver_draft_summary(season_id),
        "constructor_draft": get_constructor_draft_summary(season_id),
        "draft_scheduled_at_local": format_draft_scheduled_at_local(scheduled_at) if scheduled_at else None,
        "draft_participants": list_active_participants(),
        "order_error": None,
        "pending": list_pending_participants(),
        "participants": list_all_participants(),
        "season_timeline": get_season_timeline(int(CURRENT_SEASON)),
        "recent_race_events": list_recent_race_events(season_id) if season_id else [],
        "viewer_participant_id": request.state.current_user["participant_id"],
        "admin_action_error": None,
        "upload_success": None,
        "f1_import_success": None,
        "team_events": list_all_events(),
        "event_action_error": None,
    }


@router.get("")
def hub(request: Request, tab: str = DEFAULT_ADMIN_TAB):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")
    if not request.state.current_user.get("is_admin"):
        return RedirectResponse("/")
    if tab not in ADMIN_TABS:
        tab = DEFAULT_ADMIN_TAB

    return templates.TemplateResponse(
        request, "admin_hub.html", _build_hub_context(request, active_tab=tab)
    )


@router.get("/tab")
def admin_tab(request: Request, tab: str = DEFAULT_ADMIN_TAB):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")
    if not request.state.current_user.get("is_admin"):
        return RedirectResponse("/")
    if tab not in ADMIN_TABS:
        tab = DEFAULT_ADMIN_TAB

    return templates.TemplateResponse(
        request, "_admin_tab.html", _build_hub_context(request, active_tab=tab)
    )


@router.post("/draft/schedule")
def schedule_draft(request: Request, scheduled_at: str = Form(...)):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")
    if not request.state.current_user.get("is_owner"):
        return RedirectResponse("/admin?tab=league")

    season_id = get_season_id(CURRENT_SEASON)
    set_draft_scheduled_at(season_id, parse_draft_scheduled_at(scheduled_at))
    return RedirectResponse("/admin?tab=league", status_code=303)


@router.post("/draft/schedule/clear")
def schedule_draft_clear(request: Request):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")
    if not request.state.current_user.get("is_owner"):
        return RedirectResponse("/admin?tab=league")

    season_id = get_season_id(CURRENT_SEASON)
    set_draft_scheduled_at(season_id, None)
    return RedirectResponse("/admin?tab=league", status_code=303)


@router.post("/draft/set-order")
def set_draft_order(request: Request, order: list[str] = Form(...)):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")
    if not request.state.current_user.get("is_owner"):
        return RedirectResponse("/admin?tab=league")

    season_id = get_season_id(CURRENT_SEASON)

    try:
        save_draft_order(season_id, order, request.state.current_user["participant_id"])
    except ValueError as exc:
        context = _build_hub_context(request, active_tab="league")
        context["order_error"] = str(exc)
        return templates.TemplateResponse(request, "admin_hub.html", context)

    return RedirectResponse("/admin?tab=league", status_code=303)


@router.get("/members")
def members(request: Request):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")
    if not request.state.current_user.get("is_admin"):
        return RedirectResponse("/")

    return templates.TemplateResponse(
        request, "admin_members.html", {"pending": list_pending_participants()}
    )


@router.post("/members/{participant_id}/approve")
def approve(request: Request, participant_id: str):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")
    if not request.state.current_user.get("is_admin"):
        return RedirectResponse("/")

    approve_participant(participant_id)
    return RedirectResponse("/admin?tab=site", status_code=303)


@router.post("/members/{participant_id}/set-role")
def set_role(request: Request, participant_id: str, role: str = Form(...)):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")
    if not request.state.current_user.get("is_admin"):
        return RedirectResponse("/")

    is_owner = request.state.current_user.get("is_owner", False)
    target = get_participant(participant_id)

    if is_owner:
        # Belt-and-suspenders: the hub never renders a role-change form for
        # the Owner's own row, but reject a crafted request the same way.
        if target["role"] == ROLE_OWNER:
            context = _build_hub_context(request, active_tab="site")
            context["admin_action_error"] = "The Owner's role can't be changed."
            return templates.TemplateResponse(request, "admin_hub.html", context)
    else:
        # Admins can only toggle Member <-> Daze of Thunder Member — never
        # touch an Owner/Admin row, never grant Admin themselves.
        toggle_roles = (ROLE_MEMBER, ROLE_DOT_MEMBER)
        if target["role"] not in toggle_roles or role not in toggle_roles:
            context = _build_hub_context(request, active_tab="site")
            context["admin_action_error"] = "Only the Owner can change Admin access."
            return templates.TemplateResponse(request, "admin_hub.html", context)

    try:
        set_participant_role(participant_id, role)
    except ValueError as exc:
        context = _build_hub_context(request, active_tab="site")
        context["admin_action_error"] = str(exc)
        return templates.TemplateResponse(request, "admin_hub.html", context)

    return RedirectResponse("/admin?tab=site", status_code=303)


@router.post("/race-results/upload")
def upload_race_results(
    request: Request,
    file: UploadFile = File(...),
    ff_round_number: int = Form(...),
    supersede: bool = Form(False),
):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")
    if not request.state.current_user.get("is_admin"):  # Owner or Admin, both allowed
        return RedirectResponse("/")

    season_id = get_season_id(CURRENT_SEASON)
    timeline = get_season_timeline(int(CURRENT_SEASON))
    round_name = next(
        (r["race_name"] for r in timeline if r["round_number"] == ff_round_number), None
    )

    # Standings snapshot BEFORE scoring — import_race_json scores sim
    # points as part of the import itself, so this is the only chance to
    # capture the "before" side for the Discord post's rank movement.
    sim_before = get_sim_only_standings(season_id) if season_id else []
    constructors_before = get_constructor_standings(season_id) if season_id else []
    overall_before = get_formula_fantasy_standings(season_id) if season_id else []

    try:
        summary = import_race_json(
            file.file.read(),
            file.filename,
            season_id=season_id,
            ff_round_number=ff_round_number,
            ff_round_name=round_name,
            imported_by=request.state.current_user["participant_id"],
            supersede=supersede,
        )
    except (JsonParseError, DuplicateEventError, RoundAlreadyImportedError) as exc:
        context = _build_hub_context(request, active_tab="league")
        context["admin_action_error"] = str(exc)
        return templates.TemplateResponse(request, "admin_hub.html", context)

    if season_id and summary["scored_count"]:
        notify_sim_round(
            season_id,
            summary["race_event"]["id"],
            round_name or f"Round {ff_round_number}",
            sim_before=sim_before,
            constructors_before=constructors_before,
            overall_before=overall_before,
        )

    context = _build_hub_context(request, active_tab="league")
    context["upload_success"] = summary
    return templates.TemplateResponse(request, "admin_hub.html", context)


def _score_and_notify_rounds(season_id: str | None, summaries: list[dict]) -> list[dict]:
    """Scores every round with real data (skips any with 0 rows — an
    unreleased/unpopulated round on the schedule) and posts one Discord
    message per round to the Fantasy + Overall webhooks — called by both
    the single-round and "import all" routes, so a full backfill posts
    one message per round rather than a bulk summary."""
    if not season_id:
        return []
    timeline = get_season_timeline(int(CURRENT_SEASON))
    scored: list[dict] = []
    for s in summaries:
        if not (s["race_rows"] or s["sprint_rows"]):
            continue
        round_label = next(
            (r["race_name"] for r in timeline if r["round_number"] == s["round"]),
            f"Round {s['round']}",
        )
        scored.extend(notify_fantasy_round(season_id, s["round"], round_label))
    return scored


@router.post("/f1-results/import")
def import_f1_results(request: Request, round_number: int = Form(...)):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")
    if not request.state.current_user.get("is_admin"):  # Owner or Admin, both allowed
        return RedirectResponse("/")

    try:
        summaries = import_season(int(CURRENT_SEASON), round_number=round_number)
        season_id = get_season_id(CURRENT_SEASON)
        scored = _score_and_notify_rounds(season_id, summaries)
    except (httpx.HTTPError, ScoringRulesNotSeededError, MultipleActiveScoringRuleVersionsError) as exc:
        context = _build_hub_context(request, active_tab="league")
        context["admin_action_error"] = f"Couldn't import F1 results: {exc}"
        return templates.TemplateResponse(request, "admin_hub.html", context)

    summary = summaries[0] if summaries else {"race_rows": 0, "sprint_rows": 0}
    context = _build_hub_context(request, active_tab="league")
    context["f1_import_success"] = {
        "race_rows": summary["race_rows"],
        "sprint_rows": summary["sprint_rows"],
        "scored_count": len(scored),
    }
    return templates.TemplateResponse(request, "admin_hub.html", context)


@router.post("/f1-results/import-all")
def import_all_f1_results(request: Request):
    """One-click backfill — every completed round on the calendar, in one
    go, then scores Fantasy F1 for all of them (one Discord post per
    round scored, not a bulk summary — see _score_and_notify_rounds).
    For this beta season, fantasy scoring is deliberately allowed to
    apply retroactively (see conversation) rather than being scoped to
    rounds after the draft."""
    if not request.state.current_user:
        return RedirectResponse("/auth/login")
    if not request.state.current_user.get("is_admin"):  # Owner or Admin, both allowed
        return RedirectResponse("/")

    try:
        summaries = import_season(int(CURRENT_SEASON))
        season_id = get_season_id(CURRENT_SEASON)
        scored = _score_and_notify_rounds(season_id, summaries)
    except (httpx.HTTPError, ScoringRulesNotSeededError, MultipleActiveScoringRuleVersionsError) as exc:
        context = _build_hub_context(request, active_tab="league")
        context["admin_action_error"] = f"Couldn't import F1 results: {exc}"
        return templates.TemplateResponse(request, "admin_hub.html", context)

    context = _build_hub_context(request, active_tab="league")
    context["f1_import_success"] = {
        "race_rows": sum(s["race_rows"] for s in summaries),
        "sprint_rows": sum(s["sprint_rows"] for s in summaries),
        "rounds_with_data": sum(1 for s in summaries if s["race_rows"] or s["sprint_rows"]),
        "scored_count": len(scored),
    }
    return templates.TemplateResponse(request, "admin_hub.html", context)


@router.post("/team-events")
def create_event(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    start_date: str = Form(...),
    end_date: str = Form(...),
    car_classes: str = Form(""),
    track_name: str = Form(""),
    external_link: str = Form(""),
    image: UploadFile | None = File(None),
):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")
    if not request.state.current_user.get("is_admin"):
        return RedirectResponse("/")

    try:
        event = create_team_event(
            title=title.strip(),
            description=description.strip() or None,
            start_date=start_date,
            end_date=end_date,
            car_classes=parse_car_classes(car_classes),
            track_name=track_name.strip() or None,
            external_link=external_link.strip() or None,
            created_by=request.state.current_user["participant_id"],
        )
    except InvalidEventDateRangeError as exc:
        context = _build_hub_context(request, active_tab="team-events")
        context["event_action_error"] = str(exc)
        return templates.TemplateResponse(request, "admin_hub.html", context)

    if image and image.filename:
        try:
            upload_event_image(event["id"], image.file.read(), image.content_type)
        except InvalidImageError as exc:
            context = _build_hub_context(request, active_tab="team-events")
            context["event_action_error"] = str(exc)
            return templates.TemplateResponse(request, "admin_hub.html", context)

    return RedirectResponse("/admin?tab=team-events", status_code=303)


def _build_edit_context(event_id: str, event_action_error: str | None = None) -> dict:
    return {
        "event": get_team_event(event_id),
        "team_results": get_team_event_results(event_id),
        "event_action_error": event_action_error,
        "results_action_error": None,
    }


@router.get("/team-events/{event_id}/edit")
def edit_event_form(request: Request, event_id: str):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")
    if not request.state.current_user.get("is_admin"):
        return RedirectResponse("/")

    event = get_team_event(event_id)
    if not event:
        return RedirectResponse("/admin?tab=team-events", status_code=303)

    return templates.TemplateResponse(
        request, "admin_team_event_edit.html", _build_edit_context(event_id)
    )


@router.post("/team-events/{event_id}/edit")
def edit_event(
    request: Request,
    event_id: str,
    title: str = Form(...),
    description: str = Form(""),
    start_date: str = Form(...),
    end_date: str = Form(...),
    car_classes: str = Form(""),
    track_name: str = Form(""),
    external_link: str = Form(""),
    image: UploadFile | None = File(None),
):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")
    if not request.state.current_user.get("is_admin"):
        return RedirectResponse("/")

    try:
        update_team_event(
            event_id,
            title=title.strip(),
            description=description.strip() or None,
            start_date=start_date,
            end_date=end_date,
            car_classes=parse_car_classes(car_classes),
            track_name=track_name.strip() or None,
            external_link=external_link.strip() or None,
        )
    except InvalidEventDateRangeError as exc:
        return templates.TemplateResponse(
            request, "admin_team_event_edit.html", _build_edit_context(event_id, str(exc))
        )

    if image and image.filename:
        try:
            upload_event_image(event_id, image.file.read(), image.content_type)
        except InvalidImageError as exc:
            return templates.TemplateResponse(
                request, "admin_team_event_edit.html", _build_edit_context(event_id, str(exc))
            )

    return RedirectResponse("/admin", status_code=303)


@router.post("/team-events/{event_id}/results")
def upload_event_results(request: Request, event_id: str, file: UploadFile = File(...)):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")
    if not request.state.current_user.get("is_admin"):
        return RedirectResponse("/")

    try:
        import_team_event_results(
            event_id,
            file.file.read(),
            file.filename,
            imported_by=request.state.current_user["participant_id"],
        )
    except JsonParseError as exc:
        context = _build_edit_context(event_id)
        context["results_action_error"] = str(exc)
        return templates.TemplateResponse(request, "admin_team_event_edit.html", context)

    return RedirectResponse(f"/admin/team-events/{event_id}/edit", status_code=303)


@router.post("/team-events/{event_id}/delete")
def delete_event(request: Request, event_id: str):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")
    if not request.state.current_user.get("is_admin"):
        return RedirectResponse("/")

    delete_team_event(event_id)
    return RedirectResponse("/admin?tab=team-events", status_code=303)
