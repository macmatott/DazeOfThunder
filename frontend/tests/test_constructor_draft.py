from datetime import datetime, timezone

import pytest

from app.services.constructor_draft import (
    CONSTRUCTOR_EASTER_EGG_CELEBRATIONS,
    auto_pick_constructor_name,
    auto_pick_teammate,
    celebration_clip_index_for_pick,
    celebration_seconds_for_last_named,
    celebration_seconds_for_last_pair,
    compute_naming_status,
    compute_pairing_status,
    get_draft_finale_progress,
    get_naming_celebration_progress,
    get_pairing_celebration_progress,
    validate_captain_order,
    validate_constructor_choice,
)

CAPTAIN_ORDER = ["A", "B", "C", "D", "E"]


def _pairs(*sizes):
    """One pair dict per size in `sizes`, each with that many `members`
    entries — compute_pairing_status only reads len(), values don't
    matter. E.g. _pairs(2, 2, 3) is two 2-person teams and one 3-person
    team (the odd-roster "extra teammate" case)."""
    return [{"members": [None] * size} for size in sizes]


def test_first_captain_in_order_is_on_the_clock():
    status = compute_pairing_status(CAPTAIN_ORDER, _pairs(), 10)
    assert status == {
        "is_complete": False,
        "on_the_clock_participant_id": "A",
        "pairs_formed": 0,
        "teammates_needed": 5,
        "next_pick_number": 1,
    }


def test_next_captain_is_on_the_clock_after_a_pick():
    status = compute_pairing_status(CAPTAIN_ORDER, _pairs(2, 2), 10)
    assert status["on_the_clock_participant_id"] == "C"
    assert status["pairs_formed"] == 2
    assert status["next_pick_number"] == 3


def test_pairing_completes_once_every_captain_has_picked():
    status = compute_pairing_status(CAPTAIN_ORDER, _pairs(2, 2, 2, 2, 2), 10)
    assert status["is_complete"] is True
    assert status["on_the_clock_participant_id"] is None


def test_empty_captain_order_is_immediately_complete():
    status = compute_pairing_status([], [], 0)
    assert status["is_complete"] is True


def test_last_captain_comes_back_on_the_clock_for_an_odd_roster():
    # 11 active participants, 5 captains -> 6 teammates needed. Once
    # every captain has picked once (5 teammates assigned), one person
    # is still unassigned — the last captain in the order picks again
    # rather than that person going captain-less.
    status = compute_pairing_status(CAPTAIN_ORDER, _pairs(2, 2, 2, 2, 2), 11)
    assert status["is_complete"] is False
    assert status["on_the_clock_participant_id"] == "E"
    assert status["teammates_needed"] == 6


def test_pairing_completes_after_the_extra_pick_for_an_odd_roster():
    status = compute_pairing_status(CAPTAIN_ORDER, _pairs(2, 2, 2, 2, 3), 11)
    assert status["is_complete"] is True
    assert status["on_the_clock_participant_id"] is None


def test_validate_captain_order_accepts_floor_half_of_active_roster():
    validate_captain_order(["A", "B"], {"A", "B", "C", "D"})  # even roster, no exception
    validate_captain_order(["A", "B"], {"A", "B", "C", "D", "E"})  # odd roster, floor(5/2)=2


def test_validate_captain_order_rejects_duplicates():
    with pytest.raises(ValueError):
        validate_captain_order(["A", "A"], {"A", "B", "C", "D"})


def test_validate_captain_order_rejects_non_active_participant():
    with pytest.raises(ValueError):
        validate_captain_order(["A", "Z"], {"A", "B", "C", "D"})


def test_validate_captain_order_rejects_wrong_captain_count():
    with pytest.raises(ValueError):
        validate_captain_order(["A"], {"A", "B", "C", "D"})


def test_validate_captain_order_rejects_empty():
    with pytest.raises(ValueError):
        validate_captain_order([], {"A", "B"})


def test_auto_pick_teammate_is_alphabetically_first_other_candidate():
    available = [
        {"id": "3", "display_name": "Zed"},
        {"id": "1", "display_name": "Alice"},
        {"id": "2", "display_name": "Bob"},
    ]
    assert auto_pick_teammate(available, on_the_clock_participant_id="9") == "1"


def test_auto_pick_teammate_never_picks_the_on_the_clock_person_themselves():
    available = [
        {"id": "1", "display_name": "Alice"},
        {"id": "2", "display_name": "Bob"},
    ]
    assert auto_pick_teammate(available, on_the_clock_participant_id="1") == "2"


def test_first_unnamed_constructor_in_descending_order_is_on_the_clock():
    rows = [
        {"id": "c5", "pick_number": 5, "name": "Ferrari"},
        {"id": "c4", "pick_number": 4, "name": None},
        {"id": "c3", "pick_number": 3, "name": None},
    ]
    status = compute_naming_status(rows)
    assert status == {
        "is_complete": False,
        "on_the_clock_constructor_id": "c4",
        "current_naming_pick_number": 2,
    }


def test_naming_completes_once_every_constructor_has_a_name():
    rows = [{"id": "c1", "pick_number": 1, "name": "Williams"}]
    status = compute_naming_status(rows)
    assert status["is_complete"] is True
    assert status["on_the_clock_constructor_id"] is None


def test_naming_with_no_constructors_is_not_complete():
    # Distinct from the driver draft's empty-order case: an empty list
    # here means naming hasn't started yet (pairing isn't done), not that
    # it's finished — there's nothing to be "complete" about yet.
    status = compute_naming_status([])
    assert status["is_complete"] is False


def test_validate_constructor_choice_rejects_unknown_team():
    with pytest.raises(ValueError):
        validate_constructor_choice("Some New Team", taken_names=set())


def test_validate_constructor_choice_rejects_already_taken():
    with pytest.raises(ValueError):
        validate_constructor_choice("Ferrari", taken_names={"Ferrari"})


def test_validate_constructor_choice_accepts_available_real_team():
    validate_constructor_choice("Ferrari", taken_names={"Williams"})  # no exception


def test_auto_pick_constructor_name_is_alphabetically_first_available():
    assert auto_pick_constructor_name(["Williams", "Ferrari", "McLaren"]) == "Ferrari"


def _named(name, named_at="2026-01-01T12:00:00+00:00"):
    return {"name": name, "named_at": named_at}


def test_celebration_seconds_for_last_named_is_zero_when_empty():
    assert celebration_seconds_for_last_named([]) == 0


def test_celebration_seconds_for_last_named_is_zero_for_an_unconfigured_name():
    # Not a real constructor name, so it can never collide with a future
    # real entry in CONSTRUCTOR_EASTER_EGG_CELEBRATIONS — proves the
    # mechanism doesn't false-positive on an unconfigured team.
    assert celebration_seconds_for_last_named([_named("Some Other Team")]) == 0


def test_celebration_seconds_for_last_named_fires_once_configured(monkeypatch):
    monkeypatch.setitem(CONSTRUCTOR_EASTER_EGG_CELEBRATIONS, "Ferrari", 7)
    named = [_named("Williams"), _named("Ferrari")]
    assert celebration_seconds_for_last_named(named) == 7


def test_celebration_seconds_for_last_named_only_looks_at_the_most_recent(monkeypatch):
    monkeypatch.setitem(CONSTRUCTOR_EASTER_EGG_CELEBRATIONS, "Ferrari", 7)
    named = [_named("Ferrari"), _named("Some Other Team")]
    assert celebration_seconds_for_last_named(named) == 0


@pytest.mark.parametrize(
    "team_name",
    [
        "Ferrari",
        "McLaren",
        "Mercedes",
        "Red Bull",
        "Alpine F1 Team",
        "Aston Martin",
        "Audi",
        "Cadillac F1 Team",
        "Haas F1 Team",
        "RB F1 Team",
        "Williams",
    ],
)
def test_celebration_seconds_for_last_named_fires_on_every_easter_egg_team(team_name):
    named = [_named("Some Other Team"), _named(team_name)]
    assert celebration_seconds_for_last_named(named) == CONSTRUCTOR_EASTER_EGG_CELEBRATIONS[team_name]


def test_get_naming_celebration_progress_counts_down(monkeypatch):
    monkeypatch.setitem(CONSTRUCTOR_EASTER_EGG_CELEBRATIONS, "Ferrari", 7)
    named = [_named("Ferrari", named_at="2026-01-01T12:00:00+00:00")]
    now = datetime(2026, 1, 1, 12, 0, 3, tzinfo=timezone.utc)
    elapsed, remaining = get_naming_celebration_progress(named, now)
    assert elapsed == 3
    assert remaining == 4


def test_get_naming_celebration_progress_is_zero_without_easter_egg():
    named = [_named("Some Other Team")]
    now = datetime(2026, 1, 1, 12, 0, 3, tzinfo=timezone.utc)
    assert get_naming_celebration_progress(named, now) == (0.0, 0.0)


def _pair(pair_id, paired_at="2026-01-01T12:00:00+00:00", members=2):
    return {"id": pair_id, "paired_at": paired_at, "members": [None] * members}


def test_celebration_seconds_for_last_pair_is_zero_when_empty():
    assert celebration_seconds_for_last_pair("seed", []) == 0


def test_celebration_seconds_for_last_pair_is_zero_with_no_clips_configured(monkeypatch):
    monkeypatch.setattr("app.services.constructor_draft.PAIRING_CELEBRATION_CLIP_DURATIONS", [])
    assert celebration_seconds_for_last_pair("seed", [_pair("pair-1")]) == 0


def test_celebration_seconds_for_last_pair_uses_the_real_configured_clips():
    # PAIRING_CELEBRATION_CLIP_DURATIONS is populated now (6 real clips) —
    # every pick should get a real, in-range duration, not 0.
    duration = celebration_seconds_for_last_pair("some-draft-id", [_pair("some-real-pair-id")])
    assert duration > 0


def test_celebration_clip_index_for_pick_is_deterministic(monkeypatch):
    monkeypatch.setattr(
        "app.services.constructor_draft.PAIRING_CELEBRATION_CLIP_DURATIONS", [5, 6, 7, 8, 9]
    )
    first = celebration_clip_index_for_pick("some-draft-id", 2)
    second = celebration_clip_index_for_pick("some-draft-id", 2)
    assert first == second
    assert 0 <= first < 5


def test_celebration_clip_index_for_pick_varies_by_seed(monkeypatch):
    monkeypatch.setattr(
        "app.services.constructor_draft.PAIRING_CELEBRATION_CLIP_DURATIONS", [5, 6, 7, 8, 9]
    )
    indexes = {celebration_clip_index_for_pick(f"draft-{i}", 0) for i in range(20)}
    # Not a strict guarantee with only 20 samples across 5 buckets, but
    # overwhelmingly likely to land in more than one bucket if the shuffle
    # is actually seed-dependent, not just returning a constant.
    assert len(indexes) > 1


def test_every_configured_clip_plays_once_before_any_repeat(monkeypatch):
    durations = [5, 6, 7, 8, 9, 10]
    monkeypatch.setattr(
        "app.services.constructor_draft.PAIRING_CELEBRATION_CLIP_DURATIONS", durations
    )
    # Exactly what an 11-person league's pairing draft produces: 6
    # teammate picks (5 teams + one captain's extra pick) against 6
    # configured clips — every clip must be used, none repeated.
    indexes = [celebration_clip_index_for_pick("some-draft-id", i) for i in range(len(durations))]
    assert sorted(indexes) == list(range(len(durations)))

    # The 7th pick (if a bigger league ever needed one) wraps back
    # around to the start of the same shuffled order rather than
    # colliding with pick 0 by coincidence.
    assert celebration_clip_index_for_pick("some-draft-id", len(durations)) == indexes[0]


def test_celebration_seconds_for_last_pair_uses_the_selected_clips_duration(monkeypatch):
    durations = [5, 6, 7, 8, 9]
    monkeypatch.setattr(
        "app.services.constructor_draft.PAIRING_CELEBRATION_CLIP_DURATIONS", durations
    )
    seed = "some-draft-id"
    pairs = [_pair("pair-1"), _pair("pair-2")]
    expected_index = celebration_clip_index_for_pick(seed, 1)
    assert celebration_seconds_for_last_pair(seed, pairs) == durations[expected_index]


def test_celebration_seconds_for_last_pair_uses_pick_order_not_pair_count(monkeypatch):
    # A team's second member (the extra pick for an odd-sized roster)
    # doesn't add a new pairs row, so pick order has to come from total
    # members assigned, not len(pairs) — a 3-person team's second pick
    # is teammate pick index 1, same as if it were a 2nd distinct pair.
    durations = [5, 6, 7, 8, 9]
    monkeypatch.setattr(
        "app.services.constructor_draft.PAIRING_CELEBRATION_CLIP_DURATIONS", durations
    )
    seed = "some-draft-id"
    pairs = [_pair("pair-1", members=3)]
    expected_index = celebration_clip_index_for_pick(seed, 1)
    assert celebration_seconds_for_last_pair(seed, pairs) == durations[expected_index]


def test_get_pairing_celebration_progress_counts_down(monkeypatch):
    monkeypatch.setattr("app.services.constructor_draft.PAIRING_CELEBRATION_CLIP_DURATIONS", [10])
    pairs = [_pair("pair-1", paired_at="2026-01-01T12:00:00+00:00")]
    now = datetime(2026, 1, 1, 12, 0, 4, tzinfo=timezone.utc)
    elapsed, remaining = get_pairing_celebration_progress("seed", pairs, now)
    assert elapsed == 4
    assert remaining == 6


def test_get_pairing_celebration_progress_is_zero_without_clips_configured(monkeypatch):
    monkeypatch.setattr("app.services.constructor_draft.PAIRING_CELEBRATION_CLIP_DURATIONS", [])
    pairs = [_pair("pair-1")]
    now = datetime(2026, 1, 1, 12, 0, 4, tzinfo=timezone.utc)
    assert get_pairing_celebration_progress("seed", pairs, now) == (0.0, 0.0)


def test_get_draft_finale_progress_is_zero_when_not_complete(monkeypatch):
    monkeypatch.setattr("app.services.constructor_draft.DRAFT_FINALE_DURATION_SECONDS", 10)
    named = [_named("Ferrari")]
    now = datetime(2026, 1, 1, 12, 0, 4, tzinfo=timezone.utc)
    assert get_draft_finale_progress(named, False, now) == (0.0, 0.0)


def test_get_draft_finale_progress_is_zero_without_a_clip_configured(monkeypatch):
    monkeypatch.setattr("app.services.constructor_draft.DRAFT_FINALE_DURATION_SECONDS", 0)
    named = [_named("Ferrari")]
    now = datetime(2026, 1, 1, 12, 0, 4, tzinfo=timezone.utc)
    assert get_draft_finale_progress(named, True, now) == (0.0, 0.0)


def test_get_draft_finale_progress_uses_the_real_configured_duration():
    # DRAFT_FINALE_DURATION_SECONDS is populated now (a real clip) — a
    # draft that just finished should get a real, in-range countdown.
    named = [_named("Ferrari", named_at="2026-01-01T12:00:00+00:00")]
    now = datetime(2026, 1, 1, 12, 0, 1, tzinfo=timezone.utc)
    elapsed, remaining = get_draft_finale_progress(named, True, now)
    assert elapsed == 1
    assert remaining > 0


def test_get_draft_finale_progress_counts_down(monkeypatch):
    monkeypatch.setattr("app.services.constructor_draft.DRAFT_FINALE_DURATION_SECONDS", 10)
    named = [_named("Ferrari", named_at="2026-01-01T12:00:00+00:00")]
    now = datetime(2026, 1, 1, 12, 0, 4, tzinfo=timezone.utc)
    elapsed, remaining = get_draft_finale_progress(named, True, now)
    assert elapsed == 4
    assert remaining == 6


def test_get_draft_finale_progress_is_zero_once_the_window_passes(monkeypatch):
    monkeypatch.setattr("app.services.constructor_draft.DRAFT_FINALE_DURATION_SECONDS", 10)
    named = [_named("Ferrari", named_at="2026-01-01T12:00:00+00:00")]
    now = datetime(2026, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
    elapsed, remaining = get_draft_finale_progress(named, True, now)
    assert elapsed == 10
    assert remaining == 0
