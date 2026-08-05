from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services.participants import approve_participant, list_pending_participants

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="app/templates")


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
