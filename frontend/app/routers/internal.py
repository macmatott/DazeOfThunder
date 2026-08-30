"""
Internal, non-public routes — not linked from anywhere on the site, only
ever called by automated triggers with a shared secret.
"""

from fastapi import APIRouter, Header, HTTPException

from app.config import settings
from app.services.discord_webhooks import check_and_notify_youtube_live

router = APIRouter(prefix="/internal")


@router.post("/check-youtube-live")
def check_youtube_live(x_cron_secret: str = Header(default="")):
    """Hit on a schedule by a GitHub Actions cron (see
    .github/workflows/youtube-live-check.yml) — the site's Fly.io
    machine auto-stops when idle, so it can't run its own background
    poll loop; this cron both wakes the machine and triggers the check.
    Requires internal_cron_secret to be set and matched, so the public
    URL can't be used by anyone else to spam the channel's Discord."""
    if not settings.internal_cron_secret or x_cron_secret != settings.internal_cron_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    return {"notified": check_and_notify_youtube_live()}
