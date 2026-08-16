from datetime import datetime, timedelta, timezone

from app.services.presence import PRESENCE_TIMEOUT_SECONDS, compute_present_participant_ids

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_recent_heartbeat_counts_as_present():
    last_seen = {"A": NOW - timedelta(seconds=2)}
    assert compute_present_participant_ids(last_seen, NOW) == {"A"}


def test_stale_heartbeat_does_not_count_as_present():
    last_seen = {"A": NOW - timedelta(seconds=PRESENCE_TIMEOUT_SECONDS + 1)}
    assert compute_present_participant_ids(last_seen, NOW) == set()


def test_heartbeat_exactly_at_the_timeout_boundary_still_counts():
    last_seen = {"A": NOW - timedelta(seconds=PRESENCE_TIMEOUT_SECONDS)}
    assert compute_present_participant_ids(last_seen, NOW) == {"A"}


def test_mixes_present_and_away_participants():
    last_seen = {
        "here": NOW - timedelta(seconds=1),
        "away": NOW - timedelta(seconds=PRESENCE_TIMEOUT_SECONDS * 5),
    }
    assert compute_present_participant_ids(last_seen, NOW) == {"here"}


def test_empty_last_seen_is_empty_present_set():
    assert compute_present_participant_ids({}, NOW) == set()


def test_custom_timeout_overrides_the_default():
    last_seen = {"A": NOW - timedelta(seconds=30)}
    assert compute_present_participant_ids(last_seen, NOW, timeout_seconds=60) == {"A"}
    assert compute_present_participant_ids(last_seen, NOW, timeout_seconds=10) == set()
