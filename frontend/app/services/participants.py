"""
Participant profile — display name + iRacing identity, editable at
/profile once signed in. Reads/writes go through admin_client() (RLS on
participants is fully locked down, no policies yet) — every call here is
scoped by a participant_id/auth_user_id that the caller already verified
against our own signed session cookie, never from unverified input.
"""

from __future__ import annotations

from app.db.supabase_client import admin_client


def parse_iracing_cust_id(raw: str) -> int | None:
    raw = raw.strip()
    if not raw:
        return None
    return int(raw)


def get_participant(participant_id: str) -> dict:
    client = admin_client()
    result = client.table("participants").select("*").eq("id", participant_id).execute()
    return result.data[0]


def get_or_create_participant(auth_user_id: str, default_display_name: str) -> dict:
    client = admin_client()
    existing = (
        client.table("participants")
        .select("*")
        .eq("auth_user_id", auth_user_id)
        .execute()
    )
    if existing.data:
        return existing.data[0]

    created = (
        client.table("participants")
        .insert({"auth_user_id": auth_user_id, "display_name": default_display_name})
        .execute()
    )
    return created.data[0]


def update_participant(
    participant_id: str,
    *,
    display_name: str,
    iracing_display_name: str | None,
    iracing_cust_id: int | None,
) -> dict:
    client = admin_client()
    updated = (
        client.table("participants")
        .update(
            {
                "display_name": display_name,
                "iracing_display_name": iracing_display_name,
                "iracing_cust_id": iracing_cust_id,
            }
        )
        .eq("id", participant_id)
        .execute()
    )
    return updated.data[0]
