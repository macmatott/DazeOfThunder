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

import time

import httpx

from app.config import settings

CHANNEL_URL = "https://www.youtube.com/@DazeofThunderRacing"
CHANNEL_HANDLE = "DazeofThunderRacing"

CACHE_SECONDS = 15 * 60

_channel_id_cache: str | None = None
_live_cache: dict = {"checked_at": 0.0, "is_live": False, "video_id": None, "title": None}


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


def is_channel_live() -> bool:
    _refresh_live_cache()
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
