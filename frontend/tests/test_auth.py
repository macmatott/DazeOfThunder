import asyncio
from urllib.parse import parse_qs, urlparse

from app.services.auth import build_authorize_url, derive_display_name, refresh_session_deduped


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


# refresh_session_deduped is what stops concurrent requests holding the
# same refresh_token from racing Supabase's refresh-token rotation (see
# its docstring) — plain asyncio.run rather than pytest-asyncio, since
# nothing else in this codebase needed async tests yet.


def test_refresh_session_deduped_shares_one_call_across_concurrent_callers(monkeypatch):
    call_count = 0
    sentinel = object()

    def fake_refresh_session(token):
        nonlocal call_count
        call_count += 1
        return sentinel

    monkeypatch.setattr("app.services.auth.refresh_session", fake_refresh_session)

    async def scenario():
        return await asyncio.gather(
            refresh_session_deduped("tok-a"),
            refresh_session_deduped("tok-a"),
            refresh_session_deduped("tok-a"),
        )

    results = asyncio.run(scenario())

    assert call_count == 1
    assert results == [sentinel, sentinel, sentinel]


def test_refresh_session_deduped_returns_none_for_every_caller_on_failure(monkeypatch):
    def fake_refresh_session(token):
        raise RuntimeError("already used")

    monkeypatch.setattr("app.services.auth.refresh_session", fake_refresh_session)

    async def scenario():
        return await asyncio.gather(
            refresh_session_deduped("tok-b"),
            refresh_session_deduped("tok-b"),
        )

    assert asyncio.run(scenario()) == [None, None]


def test_refresh_session_deduped_does_not_share_calls_across_different_tokens(monkeypatch):
    calls = []

    def fake_refresh_session(token):
        calls.append(token)
        return token

    monkeypatch.setattr("app.services.auth.refresh_session", fake_refresh_session)

    async def scenario():
        return await asyncio.gather(
            refresh_session_deduped("tok-x"),
            refresh_session_deduped("tok-y"),
        )

    results = asyncio.run(scenario())

    assert sorted(calls) == ["tok-x", "tok-y"]
    assert set(results) == {"tok-x", "tok-y"}


def test_refresh_session_deduped_cleans_up_so_a_later_call_hits_supabase_again(monkeypatch):
    call_count = 0

    def fake_refresh_session(token):
        nonlocal call_count
        call_count += 1
        return call_count

    monkeypatch.setattr("app.services.auth.refresh_session", fake_refresh_session)

    async def scenario():
        first = await refresh_session_deduped("tok-z")
        second = await refresh_session_deduped("tok-z")
        return first, second

    first, second = asyncio.run(scenario())

    assert call_count == 2
    assert (first, second) == (1, 2)
