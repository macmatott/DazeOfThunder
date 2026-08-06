from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services.constructor_draft import get_constructor_draft_summary
from app.services.draft import get_driver_draft_summary, get_season_id
from app.services.f1_schedule import get_season_timeline
from app.services.iracing_ingest import (
    CsvParseError,
    DuplicateEventError,
    InvalidFilenameError,
    RoundAlreadyImportedError,
    import_race_csv,
    list_recent_race_events,
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

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="app/templates")

CURRENT_SEASON = "2026"


def _build_hub_context(request: Request) -> dict:
    season_id = get_season_id(CURRENT_SEASON)
    return {
        "season_name": CURRENT_SEASON if season_id else None,
        "driver_draft": get_driver_draft_summary(season_id),
        "constructor_draft": get_constructor_draft_summary(season_id),
        "pending": list_pending_participants(),
        "participants": list_all_participants(),
        "season_timeline": get_season_timeline(int(CURRENT_SEASON)),
        "recent_race_events": list_recent_race_events(season_id) if season_id else [],
        "viewer_participant_id": request.state.current_user["participant_id"],
        "admin_action_error": None,
        "upload_success": None,
    }


@router.get("")
def hub(request: Request):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")
    if not request.state.current_user.get("is_admin"):
        return RedirectResponse("/")

    return templates.TemplateResponse(request, "admin_hub.html", _build_hub_context(request))


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
    return RedirectResponse("/admin/members", status_code=303)


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
            context = _build_hub_context(request)
            context["admin_action_error"] = "The Owner's role can't be changed."
            return templates.TemplateResponse(request, "admin_hub.html", context)
    else:
        # Admins can only toggle Member <-> Daze of Thunder Member — never
        # touch an Owner/Admin row, never grant Admin themselves.
        toggle_roles = (ROLE_MEMBER, ROLE_DOT_MEMBER)
        if target["role"] not in toggle_roles or role not in toggle_roles:
            context = _build_hub_context(request)
            context["admin_action_error"] = "Only the Owner can change Admin access."
            return templates.TemplateResponse(request, "admin_hub.html", context)

    try:
        set_participant_role(participant_id, role)
    except ValueError as exc:
        context = _build_hub_context(request)
        context["admin_action_error"] = str(exc)
        return templates.TemplateResponse(request, "admin_hub.html", context)

    return RedirectResponse("/admin", status_code=303)


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

    try:
        summary = import_race_csv(
            file.file.read(),
            file.filename,
            season_id=season_id,
            ff_round_number=ff_round_number,
            ff_round_name=round_name,
            imported_by=request.state.current_user["participant_id"],
            supersede=supersede,
        )
    except (InvalidFilenameError, CsvParseError, DuplicateEventError, RoundAlreadyImportedError) as exc:
        context = _build_hub_context(request)
        context["admin_action_error"] = str(exc)
        return templates.TemplateResponse(request, "admin_hub.html", context)

    context = _build_hub_context(request)
    context["upload_success"] = summary
    return templates.TemplateResponse(request, "admin_hub.html", context)
