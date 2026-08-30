"""
Internal, non-public routes — not linked from anywhere on the site, only
ever called by automated triggers with a shared secret.
"""

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.services.discord_webhooks import check_and_notify_youtube_live, post_changelog

router = APIRouter(prefix="/internal")


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
