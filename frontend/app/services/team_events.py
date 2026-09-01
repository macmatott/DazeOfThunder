"""
Team Events — admin-posted iRacing special events that members RSVP to
with one of three statuses (not_interested / interested / signed_up).
Separate from race_events (imported per-race results): these are
"here's what's coming up" listings, not results.

Event images go to Supabase Storage (bucket: team-event-images, public)
rather than the bundled static/img/ files used for track/driver/team
logos — Fly.io's container filesystem is rebuilt on every deploy, so a
locally-saved upload wouldn't survive the next one.

Reads/writes go through admin_client() — every caller here is a route
that already verified the requester via the signed session cookie.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from app.db.supabase_client import admin_client
from app.services.draft import LEAGUE_TIMEZONE
from app.services.driver_photos import slugify_name
from app.services.team_event_results import get_team_event_results

EVENT_IMAGE_BUCKET = "team-event-images"

# Bundled track art (static/img/tracks/<slug>.png, same slug rule and
# same files f1_schedule.py's track_image_url uses) — lets a Team Event
# for a well-known circuit get its photo automatically instead of
# needing a manual upload.
TRACK_IMAGE_DIR = Path(__file__).resolve().parent.parent / "static" / "img" / "tracks"

VALID_RSVP_STATUSES = {"not_interested", "interested", "signed_up"}

# content-type -> file extension, both the upload allow-list and the
# storage path's suffix.
ALLOWED_IMAGE_CONTENT_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024


class InvalidRsvpStatusError(ValueError):
    pass


class InvalidImageError(ValueError):
    pass


class InvalidEventDateRangeError(ValueError):
    pass


def _validate_date_range(start_date: str, end_date: str) -> None:
    if date.fromisoformat(end_date) < date.fromisoformat(start_date):
        raise InvalidEventDateRangeError("End date can't be before the start date.")


def parse_car_classes(raw: str) -> list[str]:
    """"GT3, LMP2,  GTE" -> ["GT3", "LMP2", "GTE"] — a plain comma-
    separated text input covers "any number of car classes" without
    needing a dynamic add-a-row JS UI."""
    return [c.strip() for c in raw.split(",") if c.strip()]


def resolve_track_image_url(track_name: str | None) -> str | None:
    """"Silverstone Circuit" -> "/static/img/tracks/silverstone-circuit.png"
    if that file exists in the bundled track art, else None."""
    if not track_name:
        return None
    slug = slugify_name(track_name)
    if not (TRACK_IMAGE_DIR / f"{slug}.png").is_file():
        return None
    return f"/static/img/tracks/{slug}.png"


def resolve_track_background_url(track_name: str | None) -> str | None:
    """Same slug convention as resolve_track_image_url (<slug>-bg.jpg),
    mirroring f1_schedule.py's track_background_url — the wide/blurred
    photo shown behind the card's manually-uploaded image, existence-
    checked since most tracks don't have one yet."""
    if not track_name:
        return None
    slug = slugify_name(track_name)
    if not (TRACK_IMAGE_DIR / f"{slug}-bg.jpg").is_file():
        return None
    return f"/static/img/tracks/{slug}-bg.jpg"


_SELECT_WITH_RSVPS = (
    "id, title, description, start_date, end_date, car_classes, track_name, image_url, "
    "external_link, event_rsvps(status, participant_id, participants(display_name, role, car_number))"
)


def format_event_date_range(start_raw: str, end_raw: str) -> str:
    """Plain dates, no time-of-day. Single-day events (start == end)
    display as one date; multi-day events show the full range."""
    start = date.fromisoformat(start_raw)
    end = date.fromisoformat(end_raw)
    if start == end:
        return f"{start:%a, %b} {start.day}, {start:%Y}"
    return f"{start:%a, %b} {start.day} – {end:%a, %b} {end.day}, {end:%Y}"


def _summarize_team_result(team_results: list[dict]) -> dict | None:
    """Headline finish position + car for the card, visible without
    opening the results dropdown. Our members racing a Team Event
    together share one car/finish position, so the best (first, since
    team_results is already ordered ascending by finish_position) row
    is representative even if a car/driver name is occasionally
    missing on another row."""
    if not team_results:
        return None
    best = team_results[0]
    return {"finish_position": best["finish_position"], "car_name": best["car_name"]}


def format_session_datetime(start_time_iso: str) -> str:
    """The real session's own start time (from the JSON import), shown
    in the league's home timezone — same no-zero-pad day-of-month
    convention as format_event_date_range, e.g. "Sun, Jul 12, 2026 ·
    6:00 PM ET"."""
    dt = datetime.fromisoformat(start_time_iso).astimezone(LEAGUE_TIMEZONE)
    hour12 = dt.strftime("%I").lstrip("0") or "12"
    return f"{dt:%a, %b} {dt.day}, {dt:%Y} · {hour12}:{dt:%M %p} ET"


def _enrich_with_rsvps(events: list[dict], viewer_participant_id: str | None) -> list[dict]:
    """Attaches rsvps_by_status ({"not_interested": [...], "interested":
    [...], "signed_up": [...]}, participant dicts with display_name/role
    for role_badge) and viewer_status (the viewer's own current pick,
    None if they haven't RSVPed or aren't signed in) to each event,
    mutating in place. Shared by list_upcoming_events and
    get_event_with_rsvps so the grouping logic lives in one place."""
    for event in events:
        event["event_date_display"] = format_event_date_range(
            event["start_date"], event["end_date"]
        )
        # A track's bundled art (if any) is shown alongside the manually
        # uploaded photo, not instead of it — both can be present at once.
        event["track_image_url"] = resolve_track_image_url(event.get("track_name"))
        event["track_background_url"] = resolve_track_background_url(event.get("track_name"))
        grouped: dict[str, list[dict]] = {status: [] for status in VALID_RSVP_STATUSES}
        viewer_status = None
        for rsvp in event["event_rsvps"]:
            grouped[rsvp["status"]].append(rsvp["participants"])
            if viewer_participant_id and rsvp["participant_id"] == viewer_participant_id:
                viewer_status = rsvp["status"]
        event["rsvps_by_status"] = grouped
        event["viewer_status"] = viewer_status
        del event["event_rsvps"]
        event["team_results"] = get_team_event_results(event["id"])
        event["team_result_summary"] = _summarize_team_result(event["team_results"])

        # Real session date/time + split (e.g. "Split 2/6" for a big
        # enduro), from the JSON import — shown instead of the admin-
        # entered start_date/end_date range once we actually know when
        # our own session ran.
        session = event["team_results"][0] if event["team_results"] else None
        event["session_datetime_display"] = (
            format_session_datetime(session["session_start_time"])
            if session and session.get("session_start_time")
            else None
        )
        event["session_split_display"] = (
            f"Split {session['split_number']}/{session['split_total']}"
            if session and session.get("split_number") and session.get("split_total")
            else None
        )
        event["session_sof_display"] = (
            f"SOF {session['strength_of_field']}"
            if session and session.get("strength_of_field")
            else None
        )
    return events


def list_upcoming_events(viewer_participant_id: str | None = None) -> list[dict]:
    """Events that haven't fully ended yet (end_date >= today), ascending
    by start_date — see _enrich_with_rsvps for the per-event fields this
    attaches."""
    client = admin_client()
    today = date.today().isoformat()
    events = (
        client.table("team_events")
        .select(_SELECT_WITH_RSVPS)
        .gte("end_date", today)
        .order("start_date")
        .execute()
        .data
    )
    events = _enrich_with_rsvps(events, viewer_participant_id)
    # Already ascending by start_date, so the first row is the soonest
    # — highlighted on /schedule the same way ff_schedule.html marks
    # the next F1 race.
    if events:
        events[0]["is_next"] = True
    return events


def list_past_events(viewer_participant_id: str | None = None) -> list[dict]:
    """Events that have fully ended (end_date < today), chronological
    (oldest first) — shown as a read-only history section above the
    upcoming list on /schedule (no RSVP buttons; the picks made while
    it was still upcoming are still shown)."""
    client = admin_client()
    today = date.today().isoformat()
    events = (
        client.table("team_events")
        .select(_SELECT_WITH_RSVPS)
        .lt("end_date", today)
        .order("start_date")
        .execute()
        .data
    )
    return _enrich_with_rsvps(events, viewer_participant_id)


def _is_next_upcoming_event(event_id: str) -> bool:
    client = admin_client()
    today = date.today().isoformat()
    result = (
        client.table("team_events")
        .select("id")
        .gte("end_date", today)
        .order("start_date")
        .limit(1)
        .execute()
        .data
    )
    return bool(result) and result[0]["id"] == event_id


def get_event_with_rsvps(event_id: str, viewer_participant_id: str | None = None) -> dict | None:
    """Single event, same shape as list_upcoming_events' rows — used to
    re-render just one event's card after an RSVP POST."""
    client = admin_client()
    result = (
        client.table("team_events").select(_SELECT_WITH_RSVPS).eq("id", event_id).execute().data
    )
    if not result:
        return None
    event = _enrich_with_rsvps(result, viewer_participant_id)[0]
    event["is_next"] = _is_next_upcoming_event(event_id)
    return event


def list_all_events() -> list[dict]:
    """Every event regardless of date, chronological (oldest first) —
    for the admin hub's management list (unlike list_upcoming_events,
    admins need to see/edit past events too, e.g. to fix a typo after
    the fact)."""
    client = admin_client()
    events = (
        client.table("team_events")
        .select("id, title, start_date, end_date, image_url")
        .order("start_date")
        .execute()
        .data
    )
    for event in events:
        event["event_date_display"] = format_event_date_range(
            event["start_date"], event["end_date"]
        )
    return events


def get_team_event(event_id: str) -> dict | None:
    """For the admin edit form — start_date/end_date come back from
    Postgres as plain "YYYY-MM-DD" strings, already exactly the shape
    <input type="date"> needs for its value attribute, no reformatting
    needed."""
    client = admin_client()
    result = client.table("team_events").select("*").eq("id", event_id).execute()
    if not result.data:
        return None
    event = result.data[0]
    event["track_image_url"] = resolve_track_image_url(event.get("track_name"))
    return event


def create_team_event(
    *,
    title: str,
    description: str | None,
    start_date: str,
    end_date: str,
    car_classes: list[str],
    track_name: str | None,
    external_link: str | None,
    created_by: str,
) -> dict:
    _validate_date_range(start_date, end_date)
    client = admin_client()
    result = (
        client.table("team_events")
        .insert(
            {
                "title": title,
                "description": description,
                "start_date": start_date,
                "end_date": end_date,
                "car_classes": car_classes or None,
                "track_name": track_name,
                "external_link": external_link,
                "created_by": created_by,
            }
        )
        .execute()
    )
    return result.data[0]


def update_team_event(
    event_id: str,
    *,
    title: str,
    description: str | None,
    start_date: str,
    end_date: str,
    car_classes: list[str],
    track_name: str | None,
    external_link: str | None,
) -> dict:
    _validate_date_range(start_date, end_date)
    client = admin_client()
    result = (
        client.table("team_events")
        .update(
            {
                "title": title,
                "description": description,
                "car_classes": car_classes or None,
                "track_name": track_name,
                "start_date": start_date,
                "end_date": end_date,
                "external_link": external_link,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .eq("id", event_id)
        .execute()
    )
    return result.data[0]


def delete_team_event(event_id: str) -> None:
    client = admin_client()
    event = get_team_event(event_id)
    if event and event.get("image_url"):
        path = event["image_url"].rsplit("/", 1)[-1]
        try:
            client.storage.from_(EVENT_IMAGE_BUCKET).remove([path])
        except Exception:
            # Best-effort cleanup — a storage hiccup shouldn't block
            # deleting the event itself.
            pass
    client.table("team_events").delete().eq("id", event_id).execute()


def upload_event_image(event_id: str, file_bytes: bytes, content_type: str) -> str:
    """Uploads to Storage (upsert, so re-uploading on edit just replaces
    the file at the same path) and saves the resulting public URL onto
    the event row. Returns the public URL."""
    suffix = ALLOWED_IMAGE_CONTENT_TYPES.get(content_type)
    if not suffix:
        raise InvalidImageError(
            f"{content_type!r} isn't a supported image type — use PNG, JPEG, WEBP, or GIF."
        )
    if len(file_bytes) > MAX_IMAGE_SIZE_BYTES:
        raise InvalidImageError("Image is too large — 5MB max.")

    client = admin_client()
    path = f"{event_id}{suffix}"
    client.storage.from_(EVENT_IMAGE_BUCKET).upload(
        path, file_bytes, {"content-type": content_type, "upsert": "true"}
    )
    image_url = client.storage.from_(EVENT_IMAGE_BUCKET).get_public_url(path)
    client.table("team_events").update({"image_url": image_url}).eq("id", event_id).execute()
    return image_url


def set_rsvp(event_id: str, participant_id: str, status: str) -> dict:
    if status not in VALID_RSVP_STATUSES:
        raise InvalidRsvpStatusError(f"{status!r} isn't a valid RSVP status.")
    client = admin_client()
    result = (
        client.table("event_rsvps")
        .upsert(
            {
                "event_id": event_id,
                "participant_id": participant_id,
                "status": status,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="event_id,participant_id",
        )
        .execute()
    )
    return result.data[0]
