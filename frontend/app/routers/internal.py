"""
Internal, non-public routes — not linked from anywhere on the site, only
ever called by automated triggers with a shared secret.
"""

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.services.discord_webhooks import (
    check_and_import_new_f1_results,
    check_and_notify_youtube_live,
    check_and_post_race_week_reminder,
    post_changelog,
)

router = APIRouter(prefix="/internal")

# Matches admin.py's CURRENT_SEASON — duplicated rather than imported
# from a router module, same as every other service here that needs it.
CURRENT_SEASON = "2026"


def _require_cron_secret(x_cron_secret: str = Header(default="")) -> None:
    if not settings.internal_cron_secret or x_cron_secret != settings.internal_cron_secret:
        raise HTTPException(status_code=403, detail="Forbidden")


@router.post("/check-youtube-live", dependencies=[Depends(_require_cron_secret)])
def check_youtube_live():
    """Hit on a schedule by a GitHub Actions cron (see
    .github/workflows/youtube-live-check.yml) — the site's Fly.io
    machine auto-stops when idle, so it can't run its own background
    poll loop; this cron both wakes the machine and triggers the check."""
    return {"notified": check_and_notify_youtube_live()}


@router.post("/check-new-f1-results", dependencies=[Depends(_require_cron_secret)])
def check_new_f1_results():
    """Hit on a schedule by a GitHub Actions cron (see
    .github/workflows/f1-results-check.yml) — the same "import, score,
    notify" pipeline the admin hub's "Import F1 Results" button runs by
    hand, just triggered automatically once a real race has actually
    happened instead of needing someone to notice and click it."""
    return {"rounds_processed": check_and_import_new_f1_results(int(CURRENT_SEASON))}


@router.post("/check-race-week-reminder", dependencies=[Depends(_require_cron_secret)])
def check_race_week_reminder():
    """Hit on a schedule by a GitHub Actions cron (see
    .github/workflows/race-week-reminder.yml) — posts a "Race Week"
    reminder for the upcoming Thursday sim race, once per round (see
    check_and_post_race_week_reminder for the idempotency guard)."""
    return {"round_posted": check_and_post_race_week_reminder(int(CURRENT_SEASON))}


class PostChangelogPayload(BaseModel):
    changes: list[str]
    commit_sha: str | None = None


@router.post("/post-changelog", dependencies=[Depends(_require_cron_secret)])
def post_changelog_endpoint(payload: PostChangelogPayload):
    """Hit by the CI/CD workflow's changelog job right after a
    successful auto-deploy (see .github/scripts/post_deploy_changelog.py
    and .github/workflows/ci-cd.yml). Posting happens here, on the
    already-deployed app, rather than from the GitHub Actions runner
    itself, so discord_webhook_changelog only ever needs to be
    configured once (on Fly) instead of duplicated as a second GitHub
    secret."""
    post_changelog(payload.changes, commit_sha=payload.commit_sha)
    return {"posted": True}
