from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services.team_events import (
    InvalidRsvpStatusError,
    get_event_with_rsvps,
    list_past_events,
    list_upcoming_events,
    set_rsvp,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/schedule")
def schedule_page(request: Request):
    viewer_participant_id = None
    if request.state.current_user:
        viewer_participant_id = request.state.current_user.get("participant_id")
    events = list_upcoming_events(viewer_participant_id)
    past_events = list_past_events(viewer_participant_id)
    # list_upcoming_events already marks the soonest event is_next=True
    # and attaches its countdown/countdown_target — see
    # team_events.py::event_countdown_target — for the page's own
    # "Next Team Event" banner, same pattern as the Formula Fantasy
    # schedule page's "Next Sim Race" one.
    next_event = next((e for e in events if e.get("is_next")), None)
    return templates.TemplateResponse(
        request,
        "schedule.html",
        {
            "events": events,
            "past_events": past_events,
            "can_rsvp": bool(viewer_participant_id),
            "next_event": next_event,
        },
    )


@router.post("/schedule/{event_id}/rsvp")
def rsvp(request: Request, event_id: str, status: str = Form(...)):
    if not request.state.current_user:
        return RedirectResponse("/auth/login")
    participant_id = request.state.current_user.get("participant_id")
    if not participant_id:
        return RedirectResponse("/")

    try:
        set_rsvp(event_id, participant_id, status)
    except InvalidRsvpStatusError:
        pass

    event = get_event_with_rsvps(event_id, participant_id)
    return templates.TemplateResponse(
        request, "_team_event_card.html", {"event": event, "can_rsvp": True}
    )
