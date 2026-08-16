"""
In-memory presence tracking for the pre-draft waiting room — "who's
looking at the draft page right now". Deliberately not persisted in
Supabase: presence is inherently transient information (unlike picks,
scores, etc.), so a restart just resets everyone to "away" until their
next heartbeat — which happens within seconds, piggybacked on the
draft page's existing 2s poll rather than a dedicated ping endpoint.
A dedicated `draft_presence` table + RLS policy would be pure overhead
for data nobody ever needs to look back on.
"""

from __future__ import annotations

from datetime import datetime, timezone

# How long a heartbeat counts as "still here" — a few missed 2s polls'
# worth of grace (e.g. a poll paused because a form control has focus)
# without flickering someone to "away" between ticks.
PRESENCE_TIMEOUT_SECONDS = 8

_last_seen: dict[str, datetime] = {}


def compute_present_participant_ids(
    last_seen: dict[str, datetime], now: datetime, timeout_seconds: int = PRESENCE_TIMEOUT_SECONDS
) -> set[str]:
    """Pure function: whoever's most recent heartbeat is within
    timeout_seconds of `now`."""
    return {
        participant_id
        for participant_id, seen_at in last_seen.items()
        if (now - seen_at).total_seconds() <= timeout_seconds
    }


def record_heartbeat(participant_id: str) -> None:
    _last_seen[participant_id] = datetime.now(timezone.utc)


def get_present_participant_ids() -> set[str]:
    return compute_present_participant_ids(_last_seen, datetime.now(timezone.utc))
