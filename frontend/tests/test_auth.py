from urllib.parse import parse_qs, urlparse

from app.services.auth import build_authorize_url, derive_display_name


def test_derive_display_name_prefers_full_name():
    assert derive_display_name({"full_name": "Mac", "name": "M"}) == "Mac"


def test_derive_display_name_falls_back_to_name():
    assert derive_display_name({"name": "Mac"}) == "Mac"


def test_derive_display_name_falls_back_to_user_name():
    assert derive_display_name({"user_name": "macmatott"}) == "macmatott"


def test_derive_display_name_falls_back_to_member():
    assert derive_display_name({}) == "Member"


def test_build_authorize_url_targets_discord_pkce():
    url, verifier = build_authorize_url("http://127.0.0.1:8000/auth/callback")

    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert query["provider"] == ["discord"]
    assert query["redirect_to"] == ["http://127.0.0.1:8000/auth/callback"]
    assert query["code_challenge_method"] == ["s256"]
    assert len(query["code_challenge"][0]) > 0
    assert query["code_challenge"][0] != verifier
    assert len(verifier) > 0


def test_build_authorize_url_generates_unique_verifiers():
    _, verifier_1 = build_authorize_url("http://127.0.0.1:8000/auth/callback")
    _, verifier_2 = build_authorize_url("http://127.0.0.1:8000/auth/callback")

    assert verifier_1 != verifier_2
