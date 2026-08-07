"""
Participant profile — display name + iRacing identity, editable at
/profile once signed in. Reads/writes go through admin_client() (RLS on
participants is fully locked down, no policies yet) — every call here is
scoped by a participant_id/auth_user_id that the caller already verified
against our own signed session cookie, never from unverified input.
"""

from __future__ import annotations

from app.db.supabase_client import admin_client

ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_DOT_MEMBER = "dot_member"
ROLE_MEMBER = "member"

# Owner is excluded — it's a permanent singleton, never settable through the UI.
ASSIGNABLE_ROLES = {ROLE_ADMIN, ROLE_DOT_MEMBER, ROLE_MEMBER}


def parse_iracing_cust_id(raw: str) -> int | None:
    raw = raw.strip()
    if not raw:
        return None
    return int(raw)


def get_participant(participant_id: str) -> dict:
    client = admin_client()
    result = client.table("participants").select("*").eq("id", participant_id).execute()
    return result.data[0]


def get_participant_by_auth_user_id(auth_user_id: str) -> dict | None:
    client = admin_client()
    result = (
        client.table("participants")
        .select("*")
        .eq("auth_user_id", auth_user_id)
        .execute()
    )
    return result.data[0] if result.data else None


def get_or_create_participant(auth_user_id: str, default_display_name: str) -> dict:
    existing = get_participant_by_auth_user_id(auth_user_id)
    if existing:
        return existing

    client = admin_client()
    # New sign-ups land pending (is_active=False) until an admin approves
    # them — anyone with a Discord account can sign in, but that shouldn't
    # instantly make them a full league participant.
    created = (
        client.table("participants")
        .insert(
            {
                "auth_user_id": auth_user_id,
                "display_name": default_display_name,
                "is_active": False,
            }
        )
        .execute()
    )
    return created.data[0]


def list_pending_participants() -> list[dict]:
    """Signed-up participants awaiting admin approval (is_active=False)."""
    client = admin_client()
    result = (
        client.table("participants")
        .select("id, display_name, role, created_at")
        .eq("is_active", False)
        .order("created_at")
        .execute()
    )
    return result.data


def approve_participant(participant_id: str) -> dict:
    client = admin_client()
    updated = (
        client.table("participants")
        .update({"is_active": True})
        .eq("id", participant_id)
        .execute()
    )
    return updated.data[0]


def list_all_participants() -> list[dict]:
    """Everyone, for the admin role-management table."""
    client = admin_client()
    return (
        client.table("participants")
        .select("id, display_name, role, is_active")
        .order("display_name")
        .execute()
        .data
    )


def set_participant_role(participant_id: str, role: str) -> dict:
    if role not in ASSIGNABLE_ROLES:
        raise ValueError(f"{role!r} isn't a role you can assign.")
    client = admin_client()
    updated = (
        client.table("participants")
        .update({"role": role})
        .eq("id", participant_id)
        .execute()
    )
    return updated.data[0]


def list_iracing_cust_id_lookup() -> dict[int, str]:
    """{iracing_cust_id: participant_id} for every participant with a
    linked iRacing account — used to match CSV import rows by Cust ID."""
    client = admin_client()
    rows = (
        client.table("participants")
        .select("id, iracing_cust_id")
        .not_.is_("iracing_cust_id", "null")
        .execute()
        .data
    )
    return {row["iracing_cust_id"]: row["id"] for row in rows}


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
