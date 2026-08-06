"""
Constructor Draft — two admin-launched phases building on top of the
driver draft's turn-based/timer machinery (app/services/draft.py), reused
here rather than reimplemented:

1. Pairing: the admin sets a pick order over exactly 5 "team captains"
   (half the active roster). In that fixed order, each captain in turn
   picks one teammate from the remaining non-captains — captains never
   get skipped or "used up" by someone else's pick, since only
   non-captains are ever pickable; every captain gets exactly one turn.
   5 pairs form this way for a 10-person league.
2. Naming: order = the 5 pairs, reversed by formation order (last pair
   formed picks first) — each team claims one unclaimed real F1
   constructor name from CONSTRUCTOR_LOGOS.

Same philosophy as compute_draft_status: whose turn it is is *computed*
from constructor_draft_state.pairing_order (the captain order) + how many
constructors rows exist, never stored redundantly.
`constructor_draft_state.phase` only tracks the coarse
not_started/pairing/naming state; completion within a phase is always
derived from compute_pairing_status/compute_naming_status.
"""

from __future__ import annotations

from datetime import datetime, timezone

from postgrest.exceptions import APIError

from app.db.supabase_client import admin_client
from app.services.draft import (
    CONSTRUCTOR_LOGOS,
    DraftCompleteError,
    DraftError,
    DraftNotLiveError,
    NotYourTurnError,
    compute_seconds_remaining,
    get_turn_started_at,
    is_pick_expired,
    list_active_participants,
    logo_url_for_team,
)


def compute_pairing_status(captain_order: list[str], pairs: list[dict]) -> dict:
    """captain_order is exactly the 5 team captains, fixed at launch —
    unlike a full participant order, captains are never "used up" by
    someone else's pick, so no skip-logic is needed: the captain on the
    clock is simply captain_order[len(pairs)]. `pairs` only needs to
    support len() here (one existing pair = one captain has already
    picked)."""
    n = len(captain_order)
    pairs_formed = len(pairs)

    if n == 0 or pairs_formed >= n:
        return {
            "is_complete": True,
            "on_the_clock_participant_id": None,
            "pairs_formed": pairs_formed,
            "next_pick_number": None,
        }

    return {
        "is_complete": False,
        "on_the_clock_participant_id": captain_order[pairs_formed],
        "pairs_formed": pairs_formed,
        "next_pick_number": pairs_formed + 1,
    }


def validate_captain_order(submitted_ids: list[str], valid_ids: set[str]) -> None:
    """Captains must be a duplicate-free subset of the active roster, and
    there must be exactly half as many captains as active participants —
    each captain pairs with exactly one non-captain, with nobody left
    over on either side."""
    if not submitted_ids:
        raise ValueError("Captain order can't be empty.")
    if len(submitted_ids) != len(set(submitted_ids)):
        raise ValueError("Each participant can only be a captain once.")
    if not set(submitted_ids).issubset(valid_ids):
        raise ValueError("Captains must be current active participants.")
    if len(submitted_ids) * 2 != len(valid_ids):
        raise ValueError(
            f"Need exactly {len(valid_ids) // 2} captains for {len(valid_ids)} active participants."
        )


def compute_naming_status(constructors_desc_by_pick_number: list[dict]) -> dict:
    """Input must already be sorted by pick_number descending — that IS
    the naming turn order (last pair formed picks first). First entry
    with no name yet is on the clock."""
    total = len(constructors_desc_by_pick_number)
    for i, row in enumerate(constructors_desc_by_pick_number):
        if row["name"] is None:
            return {
                "is_complete": False,
                "on_the_clock_constructor_id": row["id"],
                "current_naming_pick_number": i + 1,
            }
    return {
        "is_complete": total > 0,
        "on_the_clock_constructor_id": None,
        "current_naming_pick_number": None,
    }


def auto_pick_teammate(
    available_partners: list[dict], on_the_clock_participant_id: str
) -> str:
    """Deterministic timeout fallback — alphabetically first available
    partner. Each dict needs {"id", "display_name"}."""
    candidates = sorted(
        (p for p in available_partners if p["id"] != on_the_clock_participant_id),
        key=lambda p: p["display_name"],
    )
    return candidates[0]["id"]


def auto_pick_constructor_name(available_names: list[str]) -> str:
    """Deterministic timeout fallback — alphabetically first unclaimed
    real F1 constructor name."""
    return sorted(available_names)[0]


def validate_constructor_choice(name: str, taken_names: set[str]) -> None:
    if name not in CONSTRUCTOR_LOGOS:
        raise ValueError(f"{name!r} isn't a real F1 constructor.")
    if name in taken_names:
        raise ValueError(f"{name!r} has already been claimed.")


def _as_timer_picks(rows: list[dict], timestamp_key: str) -> list[dict]:
    """Adapter so get_turn_started_at (which only ever reads
    picks[-1]["picked_at"]) can be reused unmodified against
    paired_at/named_at without duplicating its logic."""
    return [{"picked_at": row[timestamp_key]} for row in rows]


def get_constructor_draft_state(season_id: str) -> dict | None:
    client = admin_client()
    result = (
        client.table("constructor_draft_state").select("*").eq("season_id", season_id).execute()
    )
    return result.data[0] if result.data else None


def get_paired_participant_ids(season_id: str) -> set[str]:
    client = admin_client()
    rows = (
        client.table("constructor_members")
        .select("participant_id")
        .eq("season_id", season_id)
        .execute()
        .data
    )
    return {row["participant_id"] for row in rows}


def get_available_partners(season_id: str, captain_ids: set[str]) -> list[dict]:
    """Active participants who are neither a captain nor already claimed
    as someone's teammate — the pickable pool for whichever captain is
    on the clock."""
    already_in_a_pair = get_paired_participant_ids(season_id)
    return [
        p
        for p in list_active_participants()
        if p["id"] not in captain_ids and p["id"] not in already_in_a_pair
    ]


def get_pairs(season_id: str) -> list[dict]:
    """Formed pairs, ascending by formation order (pick_number). Each row
    is tagged with member_names (e.g. "Alice & Bob") and logo_url (once
    named)."""
    client = admin_client()
    rows = (
        client.table("constructors")
        .select(
            "id, name, pick_number, paired_at, named_at, "
            "constructor_members(participant_id, participants(display_name))"
        )
        .eq("season_id", season_id)
        .order("pick_number")
        .execute()
        .data
    )
    for row in rows:
        member_names = sorted(m["participants"]["display_name"] for m in row["constructor_members"])
        row["member_names"] = " & ".join(member_names)
        row["logo_url"] = logo_url_for_team(row["name"]) if row["name"] else None
    return rows


def get_constructors_desc_by_pick_number(season_id: str) -> list[dict]:
    """Same shape as get_pairs but descending — this IS the naming turn
    order (last pair formed picks first)."""
    return list(reversed(get_pairs(season_id)))


def launch_pairing_draft(season_id: str, ordered_captain_ids: list[str], launched_by: str) -> dict:
    valid_ids = {p["id"] for p in list_active_participants()}
    validate_captain_order(ordered_captain_ids, valid_ids)

    existing = get_constructor_draft_state(season_id)
    if existing and existing["phase"] != "not_started":
        raise ValueError("The constructor draft has already been launched.")

    client = admin_client()
    payload = {
        "season_id": season_id,
        "phase": "pairing",
        "pairing_order": ordered_captain_ids,
        "pairing_launched_at": datetime.now(timezone.utc).isoformat(),
        "launched_by": launched_by,
    }
    if existing:
        result = (
            client.table("constructor_draft_state")
            .update(payload)
            .eq("id", existing["id"])
            .execute()
        )
    else:
        result = client.table("constructor_draft_state").insert(payload).execute()
    return result.data[0]


def launch_naming_draft(season_id: str, launched_by: str) -> dict:
    state = get_constructor_draft_state(season_id)
    if not state or state["phase"] != "pairing":
        raise ValueError("Pairing hasn't been launched yet.")

    pairs = get_pairs(season_id)
    status = compute_pairing_status(state["pairing_order"], pairs)
    if not status["is_complete"]:
        raise ValueError("Pairing isn't finished yet — every team needs a partner first.")

    client = admin_client()
    payload = {
        "phase": "naming",
        "naming_launched_at": datetime.now(timezone.utc).isoformat(),
        "launched_by": launched_by,
    }
    result = (
        client.table("constructor_draft_state").update(payload).eq("id", state["id"]).execute()
    )
    return result.data[0]


def make_pairing_pick(season_id: str, captain_participant_id: str, partner_participant_id: str) -> dict:
    state = get_constructor_draft_state(season_id)
    if not state or state["phase"] != "pairing":
        raise DraftNotLiveError("The pairing draft isn't live.")

    captain_ids = set(state["pairing_order"])
    pairs = get_pairs(season_id)
    status = compute_pairing_status(state["pairing_order"], pairs)

    if status["is_complete"]:
        raise DraftCompleteError("Pairing is already complete.")
    if status["on_the_clock_participant_id"] != captain_participant_id:
        raise NotYourTurnError("It's not your turn.")
    if partner_participant_id == captain_participant_id:
        raise DraftError("You can't pick yourself as your own teammate.")
    if partner_participant_id in captain_ids:
        raise DraftError("You can only pick a non-captain as your teammate.")

    available = {p["id"] for p in get_available_partners(season_id, captain_ids)}
    if partner_participant_id not in available:
        raise DraftError("That participant has already been picked.")

    client = admin_client()
    constructor = (
        client.table("constructors")
        .insert(
            {
                "season_id": season_id,
                "pick_number": status["next_pick_number"],
                "paired_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .execute()
        .data[0]
    )
    client.table("constructor_members").insert(
        [
            {
                "constructor_id": constructor["id"],
                "participant_id": captain_participant_id,
                "season_id": season_id,
            },
            {
                "constructor_id": constructor["id"],
                "participant_id": partner_participant_id,
                "season_id": season_id,
            },
        ]
    ).execute()
    return constructor


def make_naming_pick(season_id: str, participant_id: str, name: str) -> dict:
    state = get_constructor_draft_state(season_id)
    if not state or state["phase"] != "naming":
        raise DraftNotLiveError("The naming draft isn't live.")

    constructors_desc = get_constructors_desc_by_pick_number(season_id)
    status = compute_naming_status(constructors_desc)

    if status["is_complete"]:
        raise DraftCompleteError("Naming is already complete.")

    on_the_clock = next(
        c for c in constructors_desc if c["id"] == status["on_the_clock_constructor_id"]
    )
    member_ids = {m["participant_id"] for m in on_the_clock["constructor_members"]}
    if participant_id not in member_ids:
        raise NotYourTurnError("It's not your team's turn.")

    taken_names = {c["name"] for c in constructors_desc if c["name"] is not None}
    try:
        validate_constructor_choice(name, taken_names)
    except ValueError as exc:
        raise DraftError(str(exc)) from exc

    client = admin_client()
    result = (
        client.table("constructors")
        .update({"name": name, "named_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", on_the_clock["id"])
        .execute()
    )
    return result.data[0]


def maybe_auto_pick_pairing(season_id: str) -> bool:
    """Same opportunistic-on-every-read shape as maybe_auto_pick — no
    background scheduler, checked whenever the board is read."""
    state = get_constructor_draft_state(season_id)
    if not state or state["phase"] != "pairing":
        return False

    pairs = get_pairs(season_id)
    status = compute_pairing_status(state["pairing_order"], pairs)
    if status["is_complete"]:
        return False

    turn_started_at = get_turn_started_at(
        {"launched_at": state["pairing_launched_at"]}, _as_timer_picks(pairs, "paired_at")
    )
    if not is_pick_expired(turn_started_at, datetime.now(timezone.utc)):
        return False

    captain_ids = set(state["pairing_order"])
    available = get_available_partners(season_id, captain_ids)
    if not available:
        return False

    partner_id = auto_pick_teammate(available, status["on_the_clock_participant_id"])
    try:
        make_pairing_pick(season_id, status["on_the_clock_participant_id"], partner_id)
    except (DraftError, APIError):
        pass
    return True


def maybe_auto_pick_naming(season_id: str) -> bool:
    state = get_constructor_draft_state(season_id)
    if not state or state["phase"] != "naming":
        return False

    constructors_desc = get_constructors_desc_by_pick_number(season_id)
    status = compute_naming_status(constructors_desc)
    if status["is_complete"]:
        return False

    named = [c for c in constructors_desc if c["name"] is not None]
    turn_started_at = get_turn_started_at(
        {"launched_at": state["naming_launched_at"]}, _as_timer_picks(named, "named_at")
    )
    if not is_pick_expired(turn_started_at, datetime.now(timezone.utc)):
        return False

    taken_names = {c["name"] for c in constructors_desc if c["name"] is not None}
    available = [n for n in CONSTRUCTOR_LOGOS if n not in taken_names]
    if not available:
        return False

    on_the_clock = next(
        c for c in constructors_desc if c["id"] == status["on_the_clock_constructor_id"]
    )
    any_member_id = on_the_clock["constructor_members"][0]["participant_id"]
    name = auto_pick_constructor_name(available)
    try:
        make_naming_pick(season_id, any_member_id, name)
    except (DraftError, APIError):
        pass
    return True


def build_pairing_board_context(season_id: str, viewer_participant_id: str | None) -> dict:
    maybe_auto_pick_pairing(season_id)

    state = get_constructor_draft_state(season_id)
    pairs = get_pairs(season_id)
    status = compute_pairing_status(state["pairing_order"], pairs)

    captain_ids = set(state["pairing_order"])
    available_partners = get_available_partners(season_id, captain_ids)

    on_the_clock_name = None
    if status["on_the_clock_participant_id"]:
        names = {p["id"]: p["display_name"] for p in list_active_participants()}
        on_the_clock_name = names.get(status["on_the_clock_participant_id"])

    seconds_remaining = None
    if not status["is_complete"]:
        turn_started_at = get_turn_started_at(
            {"launched_at": state["pairing_launched_at"]}, _as_timer_picks(pairs, "paired_at")
        )
        seconds_remaining = round(
            compute_seconds_remaining(turn_started_at, datetime.now(timezone.utc))
        )

    return {
        "status": status,
        "pairs": pairs,
        "available_partners": available_partners,
        "on_the_clock_name": on_the_clock_name,
        "viewer_is_on_the_clock": (
            viewer_participant_id is not None
            and status["on_the_clock_participant_id"] == viewer_participant_id
        ),
        "seconds_remaining": seconds_remaining,
    }


def build_naming_board_context(season_id: str, viewer_participant_id: str | None) -> dict:
    maybe_auto_pick_naming(season_id)

    state = get_constructor_draft_state(season_id)
    constructors_desc = get_constructors_desc_by_pick_number(season_id)
    status = compute_naming_status(constructors_desc)

    taken_names = {c["name"] for c in constructors_desc if c["name"] is not None}
    available_names = [
        {"name": name, "logo_url": logo_url_for_team(name)}
        for name in sorted(CONSTRUCTOR_LOGOS)
        if name not in taken_names
    ]

    on_the_clock_team = None
    viewer_is_on_the_clock = False
    if status["on_the_clock_constructor_id"]:
        on_the_clock_team = next(
            c for c in constructors_desc if c["id"] == status["on_the_clock_constructor_id"]
        )
        member_ids = {m["participant_id"] for m in on_the_clock_team["constructor_members"]}
        viewer_is_on_the_clock = (
            viewer_participant_id is not None and viewer_participant_id in member_ids
        )

    seconds_remaining = None
    if not status["is_complete"]:
        named = [c for c in constructors_desc if c["name"] is not None]
        turn_started_at = get_turn_started_at(
            {"launched_at": state["naming_launched_at"]}, _as_timer_picks(named, "named_at")
        )
        seconds_remaining = round(
            compute_seconds_remaining(turn_started_at, datetime.now(timezone.utc))
        )

    return {
        "status": status,
        "teams": constructors_desc,
        "available_names": available_names,
        "on_the_clock_team_label": on_the_clock_team["member_names"] if on_the_clock_team else None,
        "viewer_is_on_the_clock": viewer_is_on_the_clock,
        "seconds_remaining": seconds_remaining,
    }


def build_constructor_draft_context(season_id: str, viewer_participant_id: str | None) -> dict:
    """Single entrypoint the router calls — {phase, pairing, naming}.
    The template derives all 5 real UI states (not started / pairing
    live / pairing done awaiting naming launch / naming live / naming
    done = final results) from (phase, pairing.status.is_complete,
    naming.status.is_complete), same "computed, not stored" philosophy
    as everything else here."""
    state = get_constructor_draft_state(season_id)
    phase = state["phase"] if state else "not_started"

    pairing_ctx = None
    naming_ctx = None
    if phase == "pairing":
        pairing_ctx = build_pairing_board_context(season_id, viewer_participant_id)
    elif phase == "naming":
        naming_ctx = build_naming_board_context(season_id, viewer_participant_id)

    return {"phase": phase, "pairing": pairing_ctx, "naming": naming_ctx}
