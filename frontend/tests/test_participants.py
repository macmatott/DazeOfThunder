import pytest

from app.services.participants import parse_iracing_cust_id, set_participant_role


def test_parse_iracing_cust_id_empty_string_is_none():
    assert parse_iracing_cust_id("") is None


def test_parse_iracing_cust_id_whitespace_only_is_none():
    assert parse_iracing_cust_id("   ") is None


def test_parse_iracing_cust_id_parses_digits():
    assert parse_iracing_cust_id("123456") == 123456


def test_parse_iracing_cust_id_strips_whitespace():
    assert parse_iracing_cust_id("  123456  ") == 123456


def test_parse_iracing_cust_id_rejects_non_numeric():
    with pytest.raises(ValueError):
        parse_iracing_cust_id("abc")


def test_set_participant_role_rejects_owner():
    # Owner is a permanent singleton, never settable through this path —
    # the validation raises before any DB call is made.
    with pytest.raises(ValueError):
        set_participant_role("some-id", "owner")


def test_set_participant_role_rejects_unknown_role():
    with pytest.raises(ValueError):
        set_participant_role("some-id", "superadmin")
