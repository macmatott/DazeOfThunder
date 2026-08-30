"""
Posts race-result, standings, and changelog updates to the league's
Discord via Incoming Webhooks — one URL per channel (Drivers', Fantasy,
Constructors', Overall, and #changelog), configured in
app.config.settings. A webhook is enough here since this is one-way
(announce results, nothing reads commands back), so there's no gateway
connection or second deployment to run — a standings post happens
directly from the same admin request that triggers an F1 results
import or an iRacing results upload; a changelog post (post_changelog) is
a deliberate step taken alongside a deploy instead, since there's no CI
pipeline here to trigger it automatically off of every git push.

Fails silently everywhere: a channel whose webhook URL isn't set (e.g.
local dev) is just skipped, and a Discord outage/HTTP error never
bubbles up — an admin's results import/upload should never fail
because Discord posting didn't work.

notify_fantasy_round scores the round itself (rather than the caller
calling score_round separately) so it can snapshot standings before and
after in one place — called once per round from both the single-round
and "import all" admin routes, so a full backfill posts one message
per round instead of a bulk summary.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
from postgrest.exceptions import APIError

from app.config import settings
from app.db.supabase_client import admin_client
from app.services.standings import constructor_round_points
from app.services.youtube import get_live_stream_info

MEDALS = ["🥇", "🥈", "🥉"]
GITHUB_REPO_URL = "https://github.com/macmatott/DazeOfThunder"
SITE_URL = "https://dazeofthunder.com"


def post_to_webhook(webhook_url: str, content: str) -> None:
    if not webhook_url:
        return
    try:
        httpx.post(webhook_url, json={"content": content}, timeout=10)
    except httpx.HTTPError:
        pass


def post_changelog(
    changes: list[str],
    *,
    commit_sha: str | None = None,
    site_url: str = SITE_URL,
) -> None:
    """Posts a brief changelog synopsis to the #changelog channel —
    timestamped, linking to the live site (the homepage by default, or
    a more specific page via `site_url` when the change is localized to
    one) and to the pushed commit on GitHub (when known).

    `changes` is one or more short bullet lines for whatever shipped in
    this deploy. Prefix each with its own type emoji (✨ feature, 🐛 fix,
    🎨 style/UI, 🔧 config/infra) — the caller (a human deploying, not
    app code, since there's no CI pipeline here) decides the type, so a
    deploy bundling several kinds of change still reads as a clear list
    rather than one blurred sentence.

    Not called by any request handler — a deploy only ever happens
    because it was explicitly requested, and this is a deliberate step
    taken in that same breath rather than something triggered
    automatically off of every git push."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    parts = ["📝 **Site Update**", ""]
    parts.extend(f"• {change}" for change in changes)
    parts.append("")
    parts.append(f"🕒 {timestamp}")
    parts.append(f"🌐 {site_url}")
    if commit_sha:
        parts.append(f"🔗 {GITHUB_REPO_URL}/commit/{commit_sha}")
    post_to_webhook(settings.discord_webhook_changelog, "\n".join(parts))


def compute_standings_deltas(
    before: list[dict], after: list[dict], *, key_field: str = "participant_id"
) -> list[dict]:
    """Rank + points movement per row between two standings snapshots,
    ordered by the AFTER ranking. A row with no BEFORE entry (first time
    on the board) gets rank_change=None rather than a misleading jump."""
    before_rank = {row[key_field]: i + 1 for i, row in enumerate(before)}
    before_points = {row[key_field]: row["points"] for row in before}
    deltas = []
    for i, row in enumerate(after):
        key = row[key_field]
        old_rank = before_rank.get(key)
        old_points = before_points.get(key, 0.0)
        deltas.append(
            {
                "display_name": row["display_name"],
                "rank": i + 1,
                "rank_change": (old_rank - (i + 1)) if old_rank else None,
                "points": row["points"],
                "points_gained": round(row["points"] - old_points, 1),
            }
        )
    return deltas


def format_standings_lines(deltas: list[dict]) -> list[str]:
    lines = []
    for d in deltas:
        move = ""
        if d["rank_change"]:
            arrow = "▲" if d["rank_change"] > 0 else "▼"
            move = f" {arrow}{abs(d['rank_change'])}"
        lines.append(f"{d['rank']}. {d['display_name']} — {d['points']:.0f} pts{move}")
    return lines


def format_points_lines(deltas: list[dict]) -> list[str]:
    """Just the entities that actually gained points this round, sorted
    by how much — skips anyone at +0 (bye week / no result)."""
    gained = [d for d in deltas if d["points_gained"] > 0]
    gained.sort(key=lambda d: d["points_gained"], reverse=True)
    return [f"{d['display_name']} — +{d['points_gained']:.0f} pts" for d in gained]


def format_message(
    emoji: str,
    title: str,
    round_label: str,
    podium: list[str],
    deltas: list[dict],
) -> str:
    parts = [f"{emoji} **{title} — {round_label}**"]
    if podium:
        parts.append("  ".join(f"{MEDALS[i]} {name}" for i, name in enumerate(podium[:3])))

    points_lines = format_points_lines(deltas)
    if points_lines:
        parts.append("")
        parts.append("**Points this round**")
        parts.extend(points_lines)

    standings_lines = format_standings_lines(deltas)
    if standings_lines:
        parts.append("")
        parts.append("**Standings**")
        parts.extend(standings_lines)

    return "\n".join(parts)


def compute_fantasy_round_details(
    breakdown_by_participant: dict[str, list[dict]],
    round_number: int,
    names_by_participant: dict[str, str],
) -> list[dict]:
    """Pure: turns get_fantasy_breakdown_by_participant's full-season,
    per-driver data into just this round's breakdown — each drafted
    driver's finish position(s) and points that round, grouped by
    participant, sorted by total points earned descending. A driver
    with no result that round (bye/DNS) is omitted entirely rather than
    shown at 0, matching how the podium/points-this-round sections
    already only show what actually happened."""
    details = []
    for participant_id, drivers in breakdown_by_participant.items():
        driver_lines = []
        total = 0.0
        for driver in drivers:
            positions = driver["positions_by_round"].get(round_number, [])
            if not positions:
                continue
            points = driver["points_by_round"].get(round_number, 0)
            pos_label = "/".join(f"P{p}" for p in positions)
            driver_lines.append(f"{driver['full_name']} ({pos_label}) — {points:.0f} pts")
            total += points
        if not driver_lines:
            continue
        details.append(
            {
                "display_name": names_by_participant.get(participant_id, "Unknown"),
                "driver_lines": driver_lines,
                "total": round(total, 1),
            }
        )
    details.sort(key=lambda d: d["total"], reverse=True)
    return details


def format_breakdown_message(
    emoji: str,
    title: str,
    round_label: str,
    podium: list[str],
    round_details: list[dict],
    standings_deltas: list[dict],
) -> str:
    """Same overall shape as format_message, but "Points this round"
    breaks each entry down member-by-member (name, finish position,
    points) instead of just a flat total — used for Fantasy (per
    drafted driver) and Constructors (per teammate), since Sim/Overall
    don't have a sub-group like that to break down."""
    parts = [f"{emoji} **{title} — {round_label}**"]
    if podium:
        parts.append("  ".join(f"{MEDALS[i]} {name}" for i, name in enumerate(podium[:3])))

    if round_details:
        parts.append("")
        parts.append("**Points this round**")
        for d in round_details:
            parts.append(f"**{d['display_name']}** — +{d['total']:.0f} pts")
            parts.extend(f"↳ {line}" for line in d["driver_lines"])

    standings_lines = format_standings_lines(standings_deltas)
    if standings_lines:
        parts.append("")
        parts.append("**Standings**")
        parts.extend(standings_lines)

    return "\n".join(parts)


def compute_constructor_round_details(
    pairs: list[dict],
    points_by_participant: dict[str, float],
    position_by_participant: dict[str, int],
) -> list[dict]:
    """Pure: groups one race event's sim points/finish positions by
    constructor team, using each pair's own members list — same output
    shape as compute_fantasy_round_details (display_name, driver_lines,
    total) so both feed format_breakdown_message. A member with no
    result that event (e.g. joined the team after this round already
    ran) is omitted rather than shown at 0.

    Matches get_constructor_standings' scoring (see
    standings.py::constructor_round_points): a team's reported total is
    its top scorer's points in full plus the rounded average of every
    other member's points that round — so this league's one 3-person
    team's non-top members are listed but marked "(avg)" rather than
    one being dropped outright, since nobody's result is fully
    discarded anymore."""
    details = []
    for pair in pairs:
        scoring_members = []
        for member in pair["constructor_members"]:
            participant_id = member["participant_id"]
            if participant_id not in points_by_participant:
                continue
            scoring_members.append(
                {
                    "name": member["participants"]["display_name"],
                    "points": points_by_participant[participant_id],
                    "position": position_by_participant.get(participant_id),
                }
            )
        if not scoring_members:
            continue

        scoring_members.sort(key=lambda m: m["points"], reverse=True)
        total = constructor_round_points([m["points"] for m in scoring_members])

        def _line(m: dict, *, averaged: bool = False) -> str:
            pos_label = f"P{m['position']}" if m["position"] is not None else "?"
            suffix = " (avg)" if averaged else ""
            return f"{m['name']} ({pos_label}) — {m['points']:.0f} pts{suffix}"

        if len(scoring_members) > 2:
            top, rest = scoring_members[0], scoring_members[1:]
            member_lines = [_line(top)] + [_line(m, averaged=True) for m in rest]
        else:
            member_lines = [_line(m) for m in scoring_members]

        details.append(
            {
                "display_name": pair["name"] or pair["member_names"],
                "driver_lines": member_lines,
                "total": round(total, 1),
            }
        )
    details.sort(key=lambda d: d["total"], reverse=True)
    return details


def _f1_podium(season_id: str, round_number: int) -> list[str]:
    client = admin_client()
    rows = (
        client.table("f1_race_results")
        .select("finish_position, f1_drivers(full_name)")
        .eq("season_id", season_id)
        .eq("round_number", round_number)
        .eq("is_sprint", False)
        .not_.is_("finish_position", "null")
        .order("finish_position")
        .limit(3)
        .execute()
        .data
    )
    return [row["f1_drivers"]["full_name"] for row in rows]


def _sim_podium(race_event_id: str) -> list[str]:
    client = admin_client()
    rows = (
        client.table("race_results")
        .select("finish_position, iracing_display_name, participants(display_name)")
        .eq("race_event_id", race_event_id)
        .order("finish_position")
        .limit(3)
        .execute()
        .data
    )
    names = []
    for row in rows:
        participant = row.get("participants")
        names.append(participant["display_name"] if participant else row["iracing_display_name"])
    return names


def _constructor_round_details(season_id: str, race_event_id: str) -> list[dict]:
    from app.services.constructor_draft import get_pairs

    client = admin_client()
    points_rows = (
        client.table("sim_points_awarded")
        .select("participant_id, points")
        .eq("race_event_id", race_event_id)
        .execute()
        .data
    )
    points_by_participant = {row["participant_id"]: row["points"] for row in points_rows}

    position_rows = (
        client.table("race_results")
        .select("participant_id, finish_position")
        .eq("race_event_id", race_event_id)
        .execute()
        .data
    )
    position_by_participant = {
        row["participant_id"]: row["finish_position"]
        for row in position_rows
        if row["participant_id"]
    }

    pairs = get_pairs(season_id)
    return compute_constructor_round_details(pairs, points_by_participant, position_by_participant)


def notify_fantasy_round(season_id: str, round_number: int, round_label: str) -> list[dict]:
    """Scores one F1 round and posts to the Fantasy + Overall webhooks.
    No-ops (posts nothing) if the round has no results yet — returns
    whatever score_round returned either way ([] in that case), so
    callers can still report a scored-count without a separate
    score_round call of their own."""
    from app.services.fantasy_scoring import score_round
    from app.services.standings import get_fantasy_only_standings, get_formula_fantasy_standings

    fantasy_before = get_fantasy_only_standings(season_id)
    overall_before = get_formula_fantasy_standings(season_id)

    round_scores = score_round(season_id, round_number)
    if not round_scores:
        return []

    fantasy_after = get_fantasy_only_standings(season_id)
    overall_after = get_formula_fantasy_standings(season_id)

    from app.services.fantasy_scoring import get_fantasy_breakdown_by_participant

    names_by_participant = {row["participant_id"]: row["display_name"] for row in fantasy_after}
    breakdown_by_participant, _, _ = get_fantasy_breakdown_by_participant(season_id)
    round_details = compute_fantasy_round_details(breakdown_by_participant, round_number, names_by_participant)

    podium = _f1_podium(season_id, round_number)
    fantasy_deltas = compute_standings_deltas(fantasy_before, fantasy_after)
    post_to_webhook(
        settings.discord_webhook_fantasy,
        format_breakdown_message("🏆", "Fantasy Championship", round_label, podium, round_details, fantasy_deltas),
    )

    overall_deltas = compute_standings_deltas(overall_before, overall_after)
    post_to_webhook(
        settings.discord_webhook_overall,
        format_message("👑", "Overall Championship", round_label, [], overall_deltas),
    )
    return round_scores


def notify_sim_round(
    season_id: str,
    race_event_id: str,
    round_label: str,
    *,
    sim_before: list[dict],
    constructors_before: list[dict],
    overall_before: list[dict],
) -> None:
    """Posts to the Drivers' + Constructors' + Overall webhooks after an
    iRacing results upload. Scoring already happened inside
    import_race_json by the time this is called, so the caller
    snapshots the BEFORE standings itself (right before calling
    import_race_json) and passes them in — this function only needs to
    snapshot AFTER."""
    from app.services.standings import (
        get_constructor_standings,
        get_formula_fantasy_standings,
        get_sim_only_standings,
    )

    sim_after = get_sim_only_standings(season_id)
    constructors_after = get_constructor_standings(season_id)
    overall_after = get_formula_fantasy_standings(season_id)

    podium = _sim_podium(race_event_id)
    sim_deltas = compute_standings_deltas(sim_before, sim_after)
    post_to_webhook(
        settings.discord_webhook_drivers,
        format_message("🏎️", "Drivers' Championship", round_label, podium, sim_deltas),
    )

    constructor_details = _constructor_round_details(season_id, race_event_id)
    constructors_deltas = compute_standings_deltas(constructors_before, constructors_after, key_field="id")
    post_to_webhook(
        settings.discord_webhook_constructors,
        format_breakdown_message(
            "👥", "Constructors' Championship", round_label, [], constructor_details, constructors_deltas
        ),
    )

    overall_deltas = compute_standings_deltas(overall_before, overall_after)
    post_to_webhook(
        settings.discord_webhook_overall,
        format_message("👑", "Overall Championship", round_label, [], overall_deltas),
    )


def check_and_notify_youtube_live() -> bool:
    """Posts a "we're live" message the moment a YouTube stream is first
    seen — called from /internal/check-youtube-live, hit on a schedule
    by a GitHub Actions cron (the site's Fly.io machine auto-stops when
    idle, so it can't run its own background poll loop).

    Idempotent via youtube_live_notifications: a stream's video_id is
    only ever notified once, tracked in the DB rather than an in-memory
    flag, since the app process itself can restart mid-stream (the same
    auto-stop behavior that requires the external cron in the first
    place) and would otherwise forget it already posted. Returns
    whether a notification was actually sent, so the endpoint can
    report it."""
    info = get_live_stream_info()
    if not info:
        return False

    client = admin_client()
    try:
        client.table("youtube_live_notifications").insert({"video_id": info["video_id"]}).execute()
    except APIError as exc:
        if exc.code == "23505":  # unique_violation — already notified for this video_id
            return False
        raise

    url = f"https://www.youtube.com/watch?v={info['video_id']}"
    post_to_webhook(
        settings.discord_webhook_youtube_live,
        f"🔴 **We're live on YouTube!**\n{info['title']}\n{url}",
    )
    return True
