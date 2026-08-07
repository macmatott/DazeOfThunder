"""
2026 Fantasy Formula Draft — live, turn-based, admin-launched test run
ahead of the real 2027 draft. Whose turn it is is *computed* from
draft_state.draft_order + how many draft_picks exist (compute_draft_status)
rather than stored redundantly, so it can never drift out of sync with the
actual picks. Reads/writes go through admin_client() — every route calling
into this module has already verified who's asking via the signed session
cookie, same pattern as app/services/participants.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache

from postgrest.exceptions import APIError

from app.db.supabase_client import admin_client
from app.services.driver_photos import driver_photo_url
from app.services.fantasy_scoring import (
    ScoringRulesNotSeededError,
    get_driver_season_fantasy_stats_by_name,
)

# Order the draft pool by how drivers would have scored under our own
# fantasy scale in the previous season — real F1 points aren't used
# anywhere in the draft.
PREVIOUS_SEASON_FOR_DRAFT_ORDER = 2025

# Seconds a participant has to make their pick before the best remaining
# driver (by previous-season points, same order as the pool) is auto-picked
# for them.
PICK_TIMER_SECONDS = 30

# Seconds the intro video plays for once the owner launches the draft,
# before the first pick's clock starts — a fixed wall-clock window (not
# tied to the video's actual "ended" event) so every viewer's pick timer
# stays in sync regardless of whether their video loaded or is playing.
INTRO_DURATION_SECONDS = 60

# Easter eggs: whoever picks one of these drivers gets a celebration clip
# that plays for every viewer, not just the drafter — the next turn's
# clock is held off until it's had time to finish. Each value is the
# actual clip's measured duration (seconds), rounded up for a small
# safety margin — not a guess, re-measure if the file changes.
EASTER_EGG_CELEBRATIONS = {
    "Max Verstappen": 8,  # 7.68s at 192kbps/44100Hz CBR
    "Charles Leclerc": 6,  # 5.90s, VBR
    "Fernando Alonso": 12,  # 11.45s
    "Lewis Hamilton": 11,  # 10.46s, VBR
    "Nico Hülkenberg": 3,  # 2.02s
    "Lando Norris": 8,  # 7.63s, VBR
    "Sergio Pérez": 10,  # 9.53s, VBR
    "Oscar Piastri": 9,  # 8.57s, VBR
    "Lance Stroll": 18,  # 17.57s, .m4a
    "Andrea Kimi Antonelli": 10,  # 9.89s, .m4a
    "George Russell": 9,  # 8.21s, .m4a
    "Liam Lawson": 17,  # 16.14s
    "Isack Hadjar": 10,  # 9.40s, .m4a
    "Carlos Sainz": 8,  # 7.12s, .m4a
    "Valtteri Bottas": 10,  # 9.49s, .m4a
    "Oliver Bearman": 13,  # 12.17s, .m4a
}
VERSTAPPEN_CELEBRATION_SECONDS = EASTER_EGG_CELEBRATIONS["Max Verstappen"]

# team_name (as stored on f1_drivers, from Jolpica's Constructor.name) ->
# logo filename under app/static/img/constructors/.
CONSTRUCTOR_LOGOS = {
    "Alpine F1 Team": "alpine.png",
    "Aston Martin": "aston-martin.png",
    "Audi": "audi.png",
    "Cadillac F1 Team": "cadillac.png",
    "Ferrari": "ferrari.png",
    "Haas F1 Team": "haas.png",
    "McLaren": "mclaren.png",
    "Mercedes": "mercedes.png",
    "RB F1 Team": "rb.png",
    "Red Bull": "red-bull.png",
    "Williams": "williams.png",
}


def logo_url_for_team(team_name: str) -> str | None:
    filename = CONSTRUCTOR_LOGOS.get(team_name)
    return f"/static/img/constructors/{filename}" if filename else None


class DraftError(Exception):
    """Base for draft-flow errors the router turns into friendly messages."""


class DraftNotLiveError(DraftError):
    pass


class DraftCompleteError(DraftError):
    pass


class NotYourTurnError(DraftError):
    pass


def compute_draft_status(
    draft_order: list[str],
    total_rounds: int,
    picks: list[dict],
) -> dict:
    """
    `picks` only needs to support len() here — the count of picks already
    made is all that's needed to derive round/turn via snake-order math
    (round 2, 4, ... reverse the order).
    """
    n = len(draft_order)
    total_picks = n * total_rounds
    made = len(picks)

    if n == 0 or made >= total_picks:
        return {
            "is_complete": True,
            "current_round": None,
            "current_pick_number": None,
            "on_the_clock_participant_id": None,
        }

    round_index = made // n  # 0-based
    position_in_round = made % n
    if round_index % 2 == 1:
        position_in_round = n - 1 - position_in_round

    return {
        "is_complete": False,
        "current_round": round_index + 1,
        "current_pick_number": made + 1,
        "on_the_clock_participant_id": draft_order[position_in_round],
    }


def validate_draft_order(submitted_ids: list[str], valid_ids: set[str]) -> None:
    if not submitted_ids:
        raise ValueError("Draft order can't be empty.")
    if len(submitted_ids) != len(set(submitted_ids)):
        raise ValueError("Each participant can only appear once in the draft order.")
    if set(submitted_ids) != valid_ids:
        raise ValueError("Draft order must include every current participant exactly once.")


def get_season_id(name: str) -> str | None:
    client = admin_client()
    result = client.table("seasons").select("id").eq("name", name).execute()
    return result.data[0]["id"] if result.data else None


def get_draft_state(season_id: str) -> dict | None:
    client = admin_client()
    result = client.table("draft_state").select("*").eq("season_id", season_id).execute()
    return result.data[0] if result.data else None


def list_participants() -> list[dict]:
    """Everyone, active or pending — used for name *resolution* (e.g.
    on_the_clock_name for whoever's already in draft_order), since a
    participant's status can change after the draft launched with them
    in it. For "who's allowed to be drafted", use
    list_active_participants() instead."""
    client = admin_client()
    return (
        client.table("participants")
        .select("id, display_name, role")
        .order("display_name")
        .execute()
        .data
    )


def list_active_participants() -> list[dict]:
    """Approved participants only — the admin's draft-order dropdown and
    launch_draft's permutation check both use this, so a pending
    participant can never end up in draft_order in the first place."""
    client = admin_client()
    return (
        client.table("participants")
        .select("id, display_name, role")
        .eq("is_active", True)
        .order("display_name")
        .execute()
        .data
    )


def get_draft_picks(season_id: str) -> list[dict]:
    client = admin_client()
    picks = (
        client.table("draft_picks")
        .select(
            "pick_number, round_number, participant_id, f1_driver_id, picked_at, "
            "participants(display_name, role), f1_drivers(full_name, team_name)"
        )
        .eq("season_id", season_id)
        .order("pick_number")
        .execute()
        .data
    )
    for pick in picks:
        driver = pick["f1_drivers"]
        driver["logo_url"] = logo_url_for_team(driver["team_name"])
        driver["photo_url"] = driver_photo_url(driver["full_name"])
    return picks


def _sort_by_fantasy_points(drivers: list[dict], fantasy_stats: dict[str, dict]) -> list[dict]:
    """Ranked drivers first (highest fantasy total first); unranked
    (rookies/new teams with no previous-season results) fall to the end,
    alphabetically. Attaches `fantasy_points_2025` (season total) and
    `avg_fantasy_points_2025` (per race weekend) — both None if unranked."""
    enriched = [
        {
            **d,
            "fantasy_points_2025": fantasy_stats.get(d["full_name"], {}).get("total"),
            "avg_fantasy_points_2025": fantasy_stats.get(d["full_name"], {}).get("average"),
        }
        for d in drivers
    ]
    return sorted(
        enriched,
        key=lambda d: (
            -d["fantasy_points_2025"] if d["fantasy_points_2025"] is not None else float("inf"),
            d["full_name"],
        ),
    )


@lru_cache
def _previous_season_fantasy_stats_by_name() -> dict[str, dict]:
    """{full_name: {"total": ..., "average": ...}} for 2025, our NASCAR
    scale recomputed from that season's actual race-by-race results.
    Cached per process — a finished season's results never change. Empty
    if 2025 hasn't been imported and scored yet (import_f1_results +
    seed_scoring_rules), so the pool just won't show fantasy points rather
    than erroring."""
    season_id = get_season_id(str(PREVIOUS_SEASON_FOR_DRAFT_ORDER))
    if not season_id:
        return {}
    try:
        return get_driver_season_fantasy_stats_by_name(season_id)
    except ScoringRulesNotSeededError:
        return {}


def get_ranked_drivers(season_id: str) -> list[dict]:
    """All of the season's drivers, sorted best-to-worst by what they'd
    have scored in 2025 under our own NASCAR-style fantasy scale, each
    tagged with a fixed rank (1..22), constructor logo, and headshot photo.
    Ranks are assigned once over the *full* field so a driver's number
    stays put as other drivers get drafted, rather than being renumbered
    around the gaps."""
    client = admin_client()
    all_drivers = (
        client.table("f1_drivers")
        .select("id, full_name, team_name")
        .eq("season_id", season_id)
        .execute()
        .data
    )
    ranked = _sort_by_fantasy_points(all_drivers, _previous_season_fantasy_stats_by_name())
    for i, driver in enumerate(ranked):
        driver["rank"] = i + 1
        driver["logo_url"] = logo_url_for_team(driver["team_name"])
        driver["photo_url"] = driver_photo_url(driver["full_name"])
    return ranked


def get_available_drivers(season_id: str) -> list[dict]:
    client = admin_client()
    picked = (
        client.table("draft_picks")
        .select("f1_driver_id")
        .eq("season_id", season_id)
        .execute()
        .data
    )
    picked_ids = {row["f1_driver_id"] for row in picked}
    return [d for d in get_ranked_drivers(season_id) if d["id"] not in picked_ids]


def get_turn_started_at(
    draft_state: dict,
    picks: list[dict],
    intro_seconds: int = 0,
    celebration_seconds: int = 0,
) -> datetime:
    """The current turn's clock starts when the previous pick landed
    (plus any celebration delay), or when the draft was launched (plus
    any intro delay) if no picks have been made yet — reusing existing
    timestamps rather than storing a redundant 'turn started' column
    that could drift out of sync. Both delay params only matter for the
    driver draft; the constructor pairing/naming phases reuse this
    function via the same {"launched_at": ...} shape and never pass
    them, so they're unaffected."""
    if not picks:
        launched_at = datetime.fromisoformat(draft_state["launched_at"])
        return launched_at + timedelta(seconds=intro_seconds)
    return datetime.fromisoformat(picks[-1]["picked_at"]) + timedelta(seconds=celebration_seconds)


def compute_seconds_remaining(turn_started_at: datetime, now: datetime) -> float:
    elapsed = (now - turn_started_at).total_seconds()
    return max(0.0, PICK_TIMER_SECONDS - elapsed)


def is_pick_expired(turn_started_at: datetime, now: datetime) -> bool:
    return compute_seconds_remaining(turn_started_at, now) <= 0


def get_intro_progress(draft_state: dict, now: datetime) -> tuple[float, float]:
    """(elapsed_seconds, remaining_seconds) into the intro video window,
    both clamped to [0, INTRO_DURATION_SECONDS] — only meaningful before
    the first pick of the Driver Draft."""
    launched_at = datetime.fromisoformat(draft_state["launched_at"])
    elapsed = min(INTRO_DURATION_SECONDS, max(0.0, (now - launched_at).total_seconds()))
    return elapsed, INTRO_DURATION_SECONDS - elapsed


def celebration_seconds_for_last_pick(picks: list[dict]) -> int:
    """EASTER_EGG_CELEBRATIONS[driver] if the most recent pick was one of
    the easter-egg drivers, else 0 — 0 for an empty picks list too
    (nothing to celebrate before the first pick)."""
    if not picks:
        return 0
    return EASTER_EGG_CELEBRATIONS.get(picks[-1]["f1_drivers"]["full_name"], 0)


def get_celebration_progress(picks: list[dict], now: datetime) -> tuple[float, float]:
    """(elapsed_seconds, remaining_seconds) since the most recent pick,
    if it was the easter-egg driver — both 0 otherwise."""
    celebration_seconds = celebration_seconds_for_last_pick(picks)
    if not celebration_seconds:
        return 0.0, 0.0
    last_picked_at = datetime.fromisoformat(picks[-1]["picked_at"])
    elapsed = min(celebration_seconds, max(0.0, (now - last_picked_at).total_seconds()))
    return elapsed, celebration_seconds - elapsed


def maybe_auto_pick(season_id: str) -> bool:
    """If whoever's on the clock has run out of time, pick the best
    remaining driver (by 2025 fantasy points — same order as the pool)
    on their behalf. Checked opportunistically whenever the board is read
    (page load, poll, or after a pick) rather than via a background
    scheduler — no long-running worker exists in this deployment, and the
    board is already polled every few seconds by anyone watching."""
    state = get_draft_state(season_id)
    if not state or not state["is_live"]:
        return False

    picks = get_draft_picks(season_id)
    status = compute_draft_status(state["draft_order"], state["total_rounds"], picks)
    if status["is_complete"]:
        return False

    turn_started_at = get_turn_started_at(
        state,
        picks,
        intro_seconds=INTRO_DURATION_SECONDS,
        celebration_seconds=celebration_seconds_for_last_pick(picks),
    )
    if not is_pick_expired(turn_started_at, datetime.now(timezone.utc)):
        return False

    available = get_available_drivers(season_id)
    if not available:
        return False

    try:
        make_pick(season_id, status["on_the_clock_participant_id"], available[0]["id"])
    except (DraftError, APIError):
        # Someone else's pick (or another auto-pick) landed first — fine.
        pass
    return True


def launch_draft(
    season_id: str,
    ordered_participant_ids: list[str],
    launched_by: str,
    total_rounds: int = 2,
) -> dict:
    valid_ids = {p["id"] for p in list_active_participants()}
    validate_draft_order(ordered_participant_ids, valid_ids)

    client = admin_client()
    payload = {
        "season_id": season_id,
        "is_live": True,
        "draft_order": ordered_participant_ids,
        "total_rounds": total_rounds,
        "launched_at": datetime.now(timezone.utc).isoformat(),
        "launched_by": launched_by,
    }

    existing = get_draft_state(season_id)
    if existing:
        result = client.table("draft_state").update(payload).eq("id", existing["id"]).execute()
    else:
        result = client.table("draft_state").insert(payload).execute()
    return result.data[0]


def make_pick(season_id: str, participant_id: str, f1_driver_id: str) -> dict:
    state = get_draft_state(season_id)
    if not state or not state["is_live"]:
        raise DraftNotLiveError("The draft isn't live.")

    picks = get_draft_picks(season_id)
    now = datetime.now(timezone.utc)
    if not picks:
        _, remaining = get_intro_progress(state, now)
        if remaining > 0:
            raise DraftNotLiveError("The draft intro is still playing.")
    else:
        _, remaining = get_celebration_progress(picks, now)
        if remaining > 0:
            raise DraftNotLiveError("Still celebrating that pick — hang tight.")

    status = compute_draft_status(state["draft_order"], state["total_rounds"], picks)

    if status["is_complete"]:
        raise DraftCompleteError("The draft is already complete.")
    if status["on_the_clock_participant_id"] != participant_id:
        raise NotYourTurnError("It's not your turn.")

    client = admin_client()
    row = {
        "season_id": season_id,
        "participant_id": participant_id,
        "f1_driver_id": f1_driver_id,
        "pick_number": status["current_pick_number"],
        "round_number": status["current_round"],
    }
    result = client.table("draft_picks").insert(row).execute()
    return result.data[0]


def get_driver_draft_summary(season_id: str | None) -> dict:
    """Read-only phase snapshot for the admin hub. Deliberately doesn't
    call maybe_auto_pick the way build_draft_board_context does — a
    landing page shouldn't silently execute a pick as a side effect of
    being viewed."""
    if not season_id:
        return {"phase": "no_season"}
    state = get_draft_state(season_id)
    if not state or not state["is_live"]:
        return {"phase": "not_started"}
    picks = get_draft_picks(season_id)
    status = compute_draft_status(state["draft_order"], state["total_rounds"], picks)
    return {
        "phase": "complete" if status["is_complete"] else "live",
        "picks_made": len(picks),
        "total_picks": len(state["draft_order"]) * state["total_rounds"],
        "current_round": status["current_round"],
    }


def build_draft_board_context(season_id: str, viewer_participant_id: str | None) -> dict:
    maybe_auto_pick(season_id)

    state = get_draft_state(season_id)
    picks = get_draft_picks(season_id)
    available = get_available_drivers(season_id)

    if not state or not state["is_live"]:
        return {
            "is_live": False,
            "status": None,
            "picks": picks,
            "available_drivers": available,
            "on_the_clock_name": None,
            "viewer_is_on_the_clock": False,
            "seconds_remaining": None,
            "in_intro": False,
            "intro_seconds_remaining": None,
            "intro_elapsed_seconds": None,
            "in_celebration": False,
            "celebration_seconds_remaining": None,
        }

    status = compute_draft_status(state["draft_order"], state["total_rounds"], picks)
    now = datetime.now(timezone.utc)

    in_intro = False
    intro_seconds_remaining = None
    intro_elapsed_seconds = None
    if not picks and not status["is_complete"]:
        elapsed, remaining = get_intro_progress(state, now)
        if remaining > 0:
            in_intro = True
            intro_seconds_remaining = round(remaining)
            intro_elapsed_seconds = round(elapsed)

    in_celebration = False
    celebration_seconds_remaining = None
    if picks and not status["is_complete"]:
        _, remaining = get_celebration_progress(picks, now)
        if remaining > 0:
            in_celebration = True
            celebration_seconds_remaining = round(remaining)

    on_the_clock_name = None
    if status["on_the_clock_participant_id"]:
        names = {p["id"]: p["display_name"] for p in list_participants()}
        on_the_clock_name = names.get(status["on_the_clock_participant_id"])

    seconds_remaining = None
    if not status["is_complete"] and not in_intro and not in_celebration:
        turn_started_at = get_turn_started_at(
            state,
            picks,
            intro_seconds=INTRO_DURATION_SECONDS,
            celebration_seconds=celebration_seconds_for_last_pick(picks),
        )
        seconds_remaining = round(compute_seconds_remaining(turn_started_at, now))

    return {
        "is_live": True,
        "status": status,
        "picks": picks,
        "available_drivers": available,
        "on_the_clock_name": on_the_clock_name,
        "viewer_is_on_the_clock": (
            not in_intro
            and not in_celebration
            and viewer_participant_id is not None
            and status["on_the_clock_participant_id"] == viewer_participant_id
        ),
        "seconds_remaining": seconds_remaining,
        "in_intro": in_intro,
        "intro_seconds_remaining": intro_seconds_remaining,
        "intro_elapsed_seconds": intro_elapsed_seconds,
        "in_celebration": in_celebration,
        "celebration_seconds_remaining": celebration_seconds_remaining,
    }
