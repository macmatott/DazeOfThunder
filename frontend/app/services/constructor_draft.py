"""
Constructor Draft — two admin-launched phases building on top of the
driver draft's turn-based/timer machinery (app/services/draft.py), reused
here rather than reimplemented:

1. Pairing: the team captains are the back half of the driver draft
   order — floor(active roster / 2) of them, in that same order — no
   separate admin choice. In that fixed order, each captain in turn
   picks one teammate from the remaining non-captains — captains never
   get skipped or "used up" by someone else's pick, since only
   non-captains are ever pickable. For an even-sized roster (10
   people) that's 5 captains each picking once, forming 5 two-person
   teams. For an odd-sized roster (11 people) there's one teammate left
   over once every captain has picked once — rather than that person
   going captain-less, the *last* captain in the order picks a second
   time, so every team still ends up with a captain and every
   non-captain still ends up on a team; that captain's team is the odd
   one out at 3 members. See compute_pairing_status for the turn math.
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

import zlib
from datetime import datetime, timezone

from postgrest.exceptions import APIError

from app.db.supabase_client import admin_client
from app.services.draft import (
    CONSTRUCTOR_LOGOS,
    DraftCompleteError,
    DraftError,
    DraftNotLiveError,
    NotYourTurnError,
    build_draft_board_context,
    compute_seconds_remaining,
    get_draft_state,
    get_driver_draft_summary,
    get_turn_started_at,
    is_pick_expired,
    list_active_participants,
    logo_url_for_team,
)


def compute_pairing_status(
    captain_order: list[str], pairs: list[dict], total_active_participants: int
) -> dict:
    """captain_order is the fixed team-captain order set at launch —
    unlike a full participant order, captains are never "used up" by
    someone else's pick, so no skip-logic is needed. Whose turn it is
    is computed from how many teammates have been assigned so far
    (partners_assigned — each pair's `members` list minus its captain),
    not from how many `pairs` rows exist: a roster that doesn't split
    evenly into 2-person teams (see module docstring) leaves one
    teammate over after every captain has picked once, and that pick
    adds to an existing team rather than starting a new one, so
    `len(pairs)` alone can't tell whose turn it is once that happens.

    Round 1: each captain in captain_order picks once, in order. Any
    leftover teammates go to a second round worked through
    captain_order from the end backward, so whoever picked last in
    round 1 also picks first for the extras — that captain's team ends
    up with 3 members."""
    num_captains = len(captain_order)
    teammates_needed = total_active_participants - num_captains
    partners_assigned = sum(len(pair["members"]) - 1 for pair in pairs)

    if num_captains == 0 or partners_assigned >= teammates_needed:
        return {
            "is_complete": True,
            "on_the_clock_participant_id": None,
            "pairs_formed": partners_assigned,
            "teammates_needed": teammates_needed,
            "next_pick_number": None,
        }

    if partners_assigned < num_captains:
        on_the_clock = captain_order[partners_assigned]
    else:
        extra_index = num_captains - 1 - ((partners_assigned - num_captains) % num_captains)
        on_the_clock = captain_order[extra_index]

    return {
        "is_complete": False,
        "on_the_clock_participant_id": on_the_clock,
        "pairs_formed": partners_assigned,
        "teammates_needed": teammates_needed,
        "next_pick_number": partners_assigned + 1,
    }


# Every teammate pairing (not just special ones) gets a celebration clip
# broadcast to every viewer, randomly picked from this list — unlike the
# driver/constructor-name easter eggs, this isn't tied to who was picked.
# Each value is a clip's measured duration (seconds), rounded up for a
# small safety margin — index-aligned with the draft-pairing-clip-N audio
# tags in _draft_content.html (teammate-1.mp3 -> index 0, etc.).
PAIRING_CELEBRATION_CLIP_DURATIONS: list[int] = [2, 11, 7, 5, 5]


def celebration_clip_index_for_pair(pair_id: str) -> int:
    """Deterministic-but-effectively-random pick of one of the configured
    clips, keyed by the pair's own (UUID) id — every viewer's poll agrees
    on the same clip/duration for the same pair this way, with no extra
    storage needed. crc32 (not Python's built-in hash()) because it's
    stable across processes/restarts, not randomized per-run."""
    return zlib.crc32(pair_id.encode()) % len(PAIRING_CELEBRATION_CLIP_DURATIONS)


def celebration_seconds_for_last_pair(pairs: list[dict]) -> int:
    """The randomly-selected clip's duration for the most recently formed
    pair — 0 if no pairs yet or no clips configured."""
    if not pairs or not PAIRING_CELEBRATION_CLIP_DURATIONS:
        return 0
    index = celebration_clip_index_for_pair(pairs[-1]["id"])
    return PAIRING_CELEBRATION_CLIP_DURATIONS[index]


def get_pairing_celebration_progress(pairs: list[dict], now: datetime) -> tuple[float, float]:
    """(elapsed_seconds, remaining_seconds) since the most recently
    formed pair — both 0 if no celebration is in progress."""
    celebration_seconds = celebration_seconds_for_last_pair(pairs)
    if not celebration_seconds:
        return 0.0, 0.0
    last_paired_at = datetime.fromisoformat(pairs[-1]["paired_at"])
    elapsed = min(celebration_seconds, max(0.0, (now - last_paired_at).total_seconds()))
    return elapsed, celebration_seconds - elapsed


def validate_captain_order(submitted_ids: list[str], valid_ids: set[str]) -> None:
    """Captains must be a duplicate-free subset of the active roster, and
    there must be exactly floor(active roster / 2) of them — each
    captain picks at least one non-captain teammate, with any leftover
    (odd-sized roster) going to extra picks rather than extra captains,
    see compute_pairing_status."""
    if not submitted_ids:
        raise ValueError("Captain order can't be empty.")
    if len(submitted_ids) != len(set(submitted_ids)):
        raise ValueError("Each participant can only be a captain once.")
    if not set(submitted_ids).issubset(valid_ids):
        raise ValueError("Captains must be current active participants.")
    if len(submitted_ids) != len(valid_ids) // 2:
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


# Easter eggs: whoever claims one of these constructor names during the
# naming draft gets a celebration clip broadcast to every viewer — same
# mechanism as the driver draft's per-driver celebrations
# (app/services/draft.py::EASTER_EGG_CELEBRATIONS), just keyed by
# constructor name instead of driver name. Values are each clip's
# measured duration (seconds), rounded up for a small safety margin —
# not a guess, re-measure if a file changes. Seven teams share one
# generic "team claimed" clip (no dedicated recording for those yet).
CONSTRUCTOR_EASTER_EGG_CELEBRATIONS: dict[str, int] = {
    "Ferrari": 11,  # 10.16s, VBR
    "McLaren": 6,  # 5.67s, VBR
    "Mercedes": 4,  # 3.53s, VBR
    "Red Bull": 4,  # 3.45s
    "Alpine F1 Team": 4,  # 3.27s, VBR — shared generic clip
    "Aston Martin": 4,  # shared generic clip
    "Audi": 4,  # shared generic clip
    "Cadillac F1 Team": 4,  # shared generic clip
    "Haas F1 Team": 4,  # shared generic clip
    "RB F1 Team": 4,  # shared generic clip
    "Williams": 4,  # shared generic clip
}


def celebration_seconds_for_last_named(named: list[dict]) -> int:
    """CONSTRUCTOR_EASTER_EGG_CELEBRATIONS[name] if the most recently
    named constructor is one of the easter-egg teams, else 0 — 0 if
    nothing's been named yet. `named` must already be sorted so the
    most recently named team is last (constructors_desc filtered to
    named-only, i.e. get_constructors_desc_by_pick_number's output,
    satisfies this — same shape used everywhere else in this module)."""
    if not named:
        return 0
    return CONSTRUCTOR_EASTER_EGG_CELEBRATIONS.get(named[-1]["name"], 0)


def get_naming_celebration_progress(named: list[dict], now: datetime) -> tuple[float, float]:
    """(elapsed_seconds, remaining_seconds) since the most recently
    named constructor, if it was an easter-egg team — both 0 otherwise."""
    celebration_seconds = celebration_seconds_for_last_named(named)
    if not celebration_seconds:
        return 0.0, 0.0
    last_named_at = datetime.fromisoformat(named[-1]["named_at"])
    elapsed = min(celebration_seconds, max(0.0, (now - last_named_at).total_seconds()))
    return elapsed, celebration_seconds - elapsed


# Plays once, broadcast to every viewer, the moment the ENTIRE draft
# (Driver Draft + both Constructor Draft phases) finishes. Unlike the
# other celebrations, nothing needs to pause afterward — there's no next
# pick to hold off, since the draft is fully done. The only job this
# does is bound the effect to a short window matching the clip's own
# length, so someone opening the finished results page next week doesn't
# hear it replay — 0 means "not configured yet."
DRAFT_FINALE_DURATION_SECONDS: int = 12  # 11.34s, VBR


def get_draft_finale_progress(named: list[dict], is_complete: bool, now: datetime) -> tuple[float, float]:
    """(elapsed_seconds, remaining_seconds) since the whole draft
    finished — both 0 unless it just finished (within
    DRAFT_FINALE_DURATION_SECONDS) and a clip is configured."""
    if not is_complete or not named or not DRAFT_FINALE_DURATION_SECONDS:
        return 0.0, 0.0
    finished_at = datetime.fromisoformat(named[-1]["named_at"])
    elapsed = min(DRAFT_FINALE_DURATION_SECONDS, max(0.0, (now - finished_at).total_seconds()))
    return elapsed, DRAFT_FINALE_DURATION_SECONDS - elapsed


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
    is tagged with member_names (e.g. "Alice & Bob", for inline
    sentence-style labels like on_the_clock_team_label), members (the
    same two people as a role-aware list, for list-row rendering that
    needs to badge each name individually), and logo_url (once named)."""
    client = admin_client()
    rows = (
        client.table("constructors")
        .select(
            "id, name, pick_number, paired_at, named_at, "
            "constructor_members(participant_id, participants(display_name, role))"
        )
        .eq("season_id", season_id)
        .order("pick_number")
        .execute()
        .data
    )
    for row in rows:
        members = sorted(
            (m["participants"] for m in row["constructor_members"]),
            key=lambda p: p["display_name"],
        )
        row["members"] = members
        row["member_names"] = " & ".join(m["display_name"] for m in members)
        row["logo_url"] = logo_url_for_team(row["name"]) if row["name"] else None
    return rows


def get_constructors_desc_by_pick_number(season_id: str) -> list[dict]:
    """Same shape as get_pairs but descending — this IS the naming turn
    order (last pair formed picks first)."""
    return list(reversed(get_pairs(season_id)))


def launch_pairing_draft(season_id: str, launched_by: str) -> dict:
    # Server-side enforcement of the one-page sequential flow (Driver Draft
    # must finish before Constructor Pairing can start) — not just hidden
    # UI, since a crafted direct POST could otherwise bypass it.
    driver_summary = get_driver_draft_summary(season_id)
    if driver_summary["phase"] != "complete":
        raise ValueError("Complete the Driver Draft before launching the Constructor Draft.")

    # Captains are the back floor(N/2) picks of the driver draft order,
    # in that same order — the last people to pick a driver facilitate
    # the pairing/naming rounds, rather than an admin choosing captains
    # by hand. Floor (not half rounded up) means an odd-sized roster
    # leaves one extra non-captain rather than an extra captain — see
    # compute_pairing_status for how that extra teammate gets assigned.
    draft_order = get_draft_state(season_id)["draft_order"]
    num_captains = len(draft_order) // 2
    ordered_captain_ids = draft_order[len(draft_order) - num_captains :]

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
    total_active = len(list_active_participants())
    status = compute_pairing_status(state["pairing_order"], pairs, total_active)
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
    total_active = len(list_active_participants())
    status = compute_pairing_status(state["pairing_order"], pairs, total_active)

    if status["is_complete"]:
        raise DraftCompleteError("Pairing is already complete.")

    _, remaining = get_pairing_celebration_progress(pairs, datetime.now(timezone.utc))
    if remaining > 0:
        raise DraftNotLiveError("Still celebrating that pair — hang tight.")

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

    # An odd-sized roster means the last captain in the order comes back
    # on the clock a second time (see compute_pairing_status) — that
    # pick joins their existing team instead of starting a new one, so
    # the roster never ends up with a captain-less non-captain.
    existing = next(
        (
            pair
            for pair in pairs
            if captain_participant_id in {m["participant_id"] for m in pair["constructor_members"]}
        ),
        None,
    )
    if existing:
        client.table("constructor_members").insert(
            {
                "constructor_id": existing["id"],
                "participant_id": partner_participant_id,
                "season_id": season_id,
            }
        ).execute()
        client.table("constructors").update(
            {"paired_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", existing["id"]).execute()
        return existing

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

    named = [c for c in constructors_desc if c["name"] is not None]
    _, remaining = get_naming_celebration_progress(named, datetime.now(timezone.utc))
    if remaining > 0:
        raise DraftNotLiveError("Still celebrating that pick — hang tight.")

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
    total_active = len(list_active_participants())
    status = compute_pairing_status(state["pairing_order"], pairs, total_active)
    if status["is_complete"]:
        return False

    turn_started_at = get_turn_started_at(
        {"launched_at": state["pairing_launched_at"]},
        _as_timer_picks(pairs, "paired_at"),
        celebration_seconds=celebration_seconds_for_last_pair(pairs),
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
        {"launched_at": state["naming_launched_at"]},
        _as_timer_picks(named, "named_at"),
        celebration_seconds=celebration_seconds_for_last_named(named),
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


def get_constructor_draft_summary(season_id: str | None) -> dict:
    """Read-only phase snapshot for the admin hub — same
    doesn't-auto-pick-as-a-side-effect reasoning as
    get_driver_draft_summary in draft.py."""
    if not season_id:
        return {"phase": "no_season"}
    state = get_constructor_draft_state(season_id)
    phase = state["phase"] if state else "not_started"
    detail = None
    if phase == "pairing":
        pairs = get_pairs(season_id)
        total_active = len(list_active_participants())
        status = compute_pairing_status(state["pairing_order"], pairs, total_active)
        detail = f"{status['pairs_formed']}/{status['teammates_needed']} teammates assigned"
    elif phase == "naming":
        constructors_desc = get_constructors_desc_by_pick_number(season_id)
        status = compute_naming_status(constructors_desc)
        named = sum(1 for c in constructors_desc if c["name"])
        detail = f"{named}/{len(constructors_desc)} named"
    return {"phase": phase, "detail": detail}


def build_pairing_board_context(season_id: str, viewer_participant_id: str | None) -> dict:
    maybe_auto_pick_pairing(season_id)

    state = get_constructor_draft_state(season_id)
    pairs = get_pairs(season_id)
    total_active = len(list_active_participants())
    status = compute_pairing_status(state["pairing_order"], pairs, total_active)
    now = datetime.now(timezone.utc)

    in_celebration = False
    celebration_seconds_remaining = None
    celebration_clip_index = None
    if pairs and not status["is_complete"]:
        _, remaining = get_pairing_celebration_progress(pairs, now)
        if remaining > 0:
            in_celebration = True
            celebration_seconds_remaining = round(remaining)
            celebration_clip_index = celebration_clip_index_for_pair(pairs[-1]["id"])

    captain_ids = set(state["pairing_order"])
    available_partners = get_available_partners(season_id, captain_ids)

    on_the_clock_name = None
    if status["on_the_clock_participant_id"]:
        names = {p["id"]: p["display_name"] for p in list_active_participants()}
        on_the_clock_name = names.get(status["on_the_clock_participant_id"])

    seconds_remaining = None
    if not status["is_complete"] and not in_celebration:
        turn_started_at = get_turn_started_at(
            {"launched_at": state["pairing_launched_at"]},
            _as_timer_picks(pairs, "paired_at"),
            celebration_seconds=celebration_seconds_for_last_pair(pairs),
        )
        seconds_remaining = round(compute_seconds_remaining(turn_started_at, now))

    return {
        "status": status,
        "pairs": pairs,
        "available_partners": available_partners,
        "on_the_clock_name": on_the_clock_name,
        "viewer_is_on_the_clock": (
            not in_celebration
            and viewer_participant_id is not None
            and status["on_the_clock_participant_id"] == viewer_participant_id
        ),
        "seconds_remaining": seconds_remaining,
        "in_celebration": in_celebration,
        "celebration_seconds_remaining": celebration_seconds_remaining,
        "celebration_clip_index": celebration_clip_index,
    }


def build_naming_board_context(season_id: str, viewer_participant_id: str | None) -> dict:
    maybe_auto_pick_naming(season_id)

    state = get_constructor_draft_state(season_id)
    constructors_desc = get_constructors_desc_by_pick_number(season_id)
    status = compute_naming_status(constructors_desc)
    now = datetime.now(timezone.utc)

    named = [c for c in constructors_desc if c["name"] is not None]

    in_celebration = False
    celebration_seconds_remaining = None
    if named and not status["is_complete"]:
        _, remaining = get_naming_celebration_progress(named, now)
        if remaining > 0:
            in_celebration = True
            celebration_seconds_remaining = round(remaining)

    finale_seconds_remaining = None
    if status["is_complete"]:
        _, remaining = get_draft_finale_progress(named, status["is_complete"], now)
        if remaining > 0:
            finale_seconds_remaining = round(remaining)

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
            not in_celebration
            and viewer_participant_id is not None
            and viewer_participant_id in member_ids
        )

    seconds_remaining = None
    if not status["is_complete"] and not in_celebration:
        turn_started_at = get_turn_started_at(
            {"launched_at": state["naming_launched_at"]},
            _as_timer_picks(named, "named_at"),
            celebration_seconds=celebration_seconds_for_last_named(named),
        )
        seconds_remaining = round(compute_seconds_remaining(turn_started_at, now))

    return {
        "status": status,
        "teams": constructors_desc,
        "available_names": available_names,
        "on_the_clock_team_label": on_the_clock_team["member_names"] if on_the_clock_team else None,
        "viewer_is_on_the_clock": viewer_is_on_the_clock,
        "seconds_remaining": seconds_remaining,
        "in_celebration": in_celebration,
        "celebration_seconds_remaining": celebration_seconds_remaining,
        "last_named_team_name": named[-1]["name"] if named else None,
        "named_count": len(named),
        "finale_seconds_remaining": finale_seconds_remaining,
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


def build_combined_draft_context(season_id: str, viewer_participant_id: str | None) -> dict:
    """Everything /formula-fantasy/draft needs to render both halves of
    the merged Driver + Constructor draft flow in one call — used by
    both the page route and its polling partial so the "Driver Draft
    finished, reveal the Constructor Draft" transition updates live for
    everyone watching instead of needing a manual refresh."""
    return {
        "board": build_draft_board_context(season_id, viewer_participant_id),
        **build_constructor_draft_context(season_id, viewer_participant_id),
    }
