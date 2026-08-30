"""
Parses the latest commit message into changelog bullets and posts them
to the deployed app's /internal/post-changelog endpoint, which does the
actual Discord post using the webhook URL already configured on Fly —
this stays a standalone, dependency-free script (stdlib only) rather
than importing the app package, so discord_webhook_changelog only ever
needs to be configured once instead of duplicated as a second GitHub
secret, and this job doesn't need a pip install step at all.

A well-written commit message IS the changelog here; there's no
separate "write changelog bullets" step. Blank-line-separated
paragraphs become separate bullets (so a commit covering several
distinct changes still reads as a list, not one run-on paragraph); a
trailing "Co-Authored-By:" trailer is stripped since it's git
bookkeeping, not a change worth announcing.

Run by the CI/CD workflow's changelog job right after a successful
auto-deploy (see ../workflows/ci-cd.yml).
"""

import json
import os
import subprocess
import urllib.error
import urllib.request

SITE_URL = "https://dazeofthunder.com"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _changes_from_commit_message(message: str) -> list[str]:
    lines = [line for line in message.splitlines() if not line.startswith("Co-Authored-By:")]
    body = "\n".join(lines).strip()
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    # Git wraps a commit body at ~72 columns — collapse each paragraph's
    # hard line-wraps back into one flowing line, so a single bullet
    # doesn't visually fracture into unprefixed continuation lines in
    # Discord (post_changelog only prefixes "• " once per list entry).
    return [" ".join(p.splitlines()) for p in paragraphs]


def main() -> None:
    changes = _changes_from_commit_message(_git("log", "-1", "--pretty=%B"))
    if not changes:
        print("Empty commit message after stripping trailers — nothing to post.")
        return

    payload = json.dumps({"changes": changes, "commit_sha": _git("rev-parse", "HEAD")}).encode()
    request = urllib.request.Request(
        f"{SITE_URL}/internal/post-changelog",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Cron-Secret": os.environ["INTERNAL_CRON_SECRET"],
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            print(f"Posted {len(changes)} change(s) to the changelog channel ({response.status}).")
    except urllib.error.HTTPError as exc:
        print(f"Failed to post changelog: {exc.code} {exc.read().decode(errors='replace')}")
        raise


if __name__ == "__main__":
    main()
