"""
"Are we live on YouTube" check, shared by the nav's YouTube box
(is_channel_live) and the Discord "went live" notification
(get_live_stream_info, see discord_webhooks.py). Polled at most once
per CACHE_SECONDS and cached in-memory — search.list (the only
official endpoint that reports live status for an arbitrary channel)
costs 100 quota units per call against YouTube's default 10,000/day
budget, so polling on every request would blow through it in minutes.
Both callers share the same cached refresh rather than each polling
independently.

Fails closed (reports offline) on any error — missing API key, network
hiccup, quota exceeded — so a YouTube outage never breaks the page.
"""

from __future__ import annotations

import asyncio
import time

import httpx

from app.config import settings

CHANNEL_URL = "https://www.youtube.com/@DazeofThunderRacing"
CHANNEL_HANDLE = "DazeofThunderRacing"

CACHE_SECONDS = 15 * 60

_channel_id_cache: str | None = None
_live_cache: dict = {"checked_at": 0.0, "is_live": False, "video_id": None, "title": None}
_background_refresh_task: "asyncio.Task | None" = None


def _resolve_channel_id(client: httpx.Client) -> str | None:
    global _channel_id_cache
    if _channel_id_cache is not None:
        return _channel_id_cache

    resp = client.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={"part": "id", "forHandle": CHANNEL_HANDLE, "key": settings.youtube_api_key},
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if not items:
        return None
    _channel_id_cache = items[0]["id"]
    return _channel_id_cache


def _refresh_live_cache() -> None:
    """The actual API call, at most once per CACHE_SECONDS regardless of
    how many callers ask — is_channel_live() (the nav indicator) and
    get_live_stream_info() (the Discord "went live" check) share this
    same cache/quota budget rather than each polling independently."""
    now = time.time()
    if now - _live_cache["checked_at"] < CACHE_SECONDS:
        return

    live, video_id, title = False, None, None
    if settings.youtube_api_key:
        try:
            with httpx.Client(timeout=5.0) as client:
                channel_id = _resolve_channel_id(client)
                if channel_id:
                    resp = client.get(
                        "https://www.googleapis.com/youtube/v3/search",
                        params={
                            "part": "snippet",
                            "channelId": channel_id,
                            "eventType": "live",
                            "type": "video",
                            "key": settings.youtube_api_key,
                        },
                    )
                    resp.raise_for_status()
                    items = resp.json().get("items", [])
                    if items:
                        live = True
                        video_id = items[0]["id"]["videoId"]
                        title = items[0]["snippet"]["title"]
        except httpx.HTTPError:
            live = False

    _live_cache.update(checked_at=now, is_live=live, video_id=video_id, title=title)


def ensure_live_cache_fresh_soon() -> None:
    """Kicks off a background refresh if the cache is stale and nothing
    is already refreshing it — never awaited by the caller, so a cold
    cache (a fresh process that's never checked yet, or just the
    15-minute mark) never blocks the page request that happens to
    trigger it.

    This matters because _live_cache is a plain in-memory dict: it
    resets to empty on every process restart, so — before this existed
    — the very first request after any deploy or Fly.io cold start
    (the app's machine auto-stops when idle) paid the *real* API round
    trip (up to two sequential calls, each with a 5s timeout) inline,
    stacked right on top of however long the cold start itself already
    took. Now that request just sees the last-known (or default
    "offline") value immediately, same as every other request; correct
    data shows up on the *next* request once the background refresh
    finishes, typically well under a second later.

    Only the nav indicator (is_channel_live, called from
    CurrentUserMiddleware on every request) needs this — the Discord
    "went live" check (get_live_stream_info) is only ever called from a
    cron-triggered background job, not a page response, so it still
    calls _refresh_live_cache directly and waits for a real answer."""
    global _background_refresh_task
    now = time.time()
    if now - _live_cache["checked_at"] < CACHE_SECONDS:
        return
    if _background_refresh_task is None or _background_refresh_task.done():
        _background_refresh_task = asyncio.ensure_future(asyncio.to_thread(_refresh_live_cache))


def is_channel_live() -> bool:
    ensure_live_cache_fresh_soon()
    return bool(_live_cache["is_live"])


def get_live_stream_info() -> dict | None:
    """{"video_id": ..., "title": ...} if the channel is currently live,
    else None. Same 15-minute cache as is_channel_live() — calling this
    never triggers an extra API call beyond what the nav indicator
    already causes."""
    _refresh_live_cache()
    if not _live_cache["is_live"]:
        return None
    return {"video_id": _live_cache["video_id"], "title": _live_cache["title"]}
