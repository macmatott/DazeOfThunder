import pytest

from app.services.team_events import (
    MAX_IMAGE_SIZE_BYTES,
    InvalidEventDateRangeError,
    InvalidImageError,
    InvalidRsvpStatusError,
    create_team_event,
    format_event_date_range,
    parse_car_classes,
    resolve_track_image_url,
    set_rsvp,
    update_team_event,
    upload_event_image,
)


def test_upload_event_image_rejects_unsupported_content_type():
    with pytest.raises(InvalidImageError):
        upload_event_image("event-1", b"not-an-image", "application/pdf")


def test_upload_event_image_rejects_oversized_file():
    oversized = b"x" * (MAX_IMAGE_SIZE_BYTES + 1)
    with pytest.raises(InvalidImageError):
        upload_event_image("event-1", oversized, "image/png")


def test_set_rsvp_rejects_invalid_status():
    with pytest.raises(InvalidRsvpStatusError):
        set_rsvp("event-1", "participant-1", "maybe")


def test_format_event_date_range_single_day():
    assert format_event_date_range("2026-09-01", "2026-09-01") == "Tue, Sep 1, 2026"


def test_format_event_date_range_multi_day():
    assert (
        format_event_date_range("2026-09-01", "2026-09-05")
        == "Tue, Sep 1 – Sat, Sep 5, 2026"
    )


def test_create_team_event_rejects_end_before_start():
    with pytest.raises(InvalidEventDateRangeError):
        create_team_event(
            title="Bad Event",
            description=None,
            start_date="2026-09-05",
            end_date="2026-09-01",
            car_classes=[],
            track_name=None,
            external_link=None,
            created_by="participant-1",
        )


def test_update_team_event_rejects_end_before_start():
    with pytest.raises(InvalidEventDateRangeError):
        update_team_event(
            "event-1",
            title="Bad Event",
            description=None,
            start_date="2026-09-05",
            end_date="2026-09-01",
            car_classes=[],
            track_name=None,
            external_link=None,
        )


def test_parse_car_classes_splits_and_trims():
    assert parse_car_classes("GT3, LMP2,  GTE") == ["GT3", "LMP2", "GTE"]


def test_parse_car_classes_drops_empty_entries():
    assert parse_car_classes("GT3, , GTE,") == ["GT3", "GTE"]


def test_parse_car_classes_empty_string():
    assert parse_car_classes("") == []


def test_resolve_track_image_url_matches_bundled_file():
    assert resolve_track_image_url("Silverstone Circuit") == "/static/img/tracks/silverstone-circuit.png"


def test_resolve_track_image_url_no_match_returns_none():
    assert resolve_track_image_url("Nonexistent Speedway") is None


def test_resolve_track_image_url_empty_input_returns_none():
    assert resolve_track_image_url(None) is None
    assert resolve_track_image_url("") is None
