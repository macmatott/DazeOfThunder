"""
"Are we live on YouTube" check for the nav's YouTube box. Polled at most
once per CACHE_SECONDS and cached in-memory — search.list (the only
official endpoint that reports live status for an arbitrary channel)
costs 100 quota units per call against YouTube's default 10,000/day
budget, so polling on every request would blow through it in minutes.

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
_live_cache: dict[str, float | bool] = {"checked_at": 0.0, "is_live": False}


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


def is_channel_live() -> bool:
    now = time.time()
    if now - _live_cache["checked_at"] < CACHE_SECONDS:
        return bool(_live_cache["is_live"])

    live = False
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
                    live = bool(resp.json().get("items"))
        except httpx.HTTPError:
            live = False

    _live_cache["checked_at"] = now
    _live_cache["is_live"] = live
    return live
