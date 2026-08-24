import base64
import hashlib
import time
import urllib.parse

import pytest

from yoto_iconer import auth, config


def test_pkce_challenge_is_the_sha256_of_the_verifier():
    verifier, challenge = auth.pkce_pair()
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    assert challenge == expected


def test_pkce_verifier_is_unpadded_and_long_enough():
    verifier, _ = auth.pkce_pair()
    assert "=" not in verifier and 43 <= len(verifier) <= 128


def test_authorize_url_carries_the_required_params():
    url = auth.authorize_url("CID", "CHAL", "STATE")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q["client_id"] == ["CID"]
    assert q["code_challenge_method"] == ["S256"]
    assert q["redirect_uri"] == [config.REDIRECT_URI]
    assert q["audience"] == [config.AUDIENCE]
    assert "offline_access" in q["scope"][0]
    assert "user:content:manage" in q["scope"][0]


def test_tokens_round_trip_and_are_private():
    auth.save_tokens({"access_token": "a", "refresh_token": "r", "expires_at": 1})
    assert auth.load_tokens()["refresh_token"] == "r"
    assert oct(config.tokens_path().stat().st_mode)[-3:] == "600"


def test_store_grant_keeps_old_refresh_token_when_none_returned():
    tokens = auth._store_grant(
        {"access_token": "new", "expires_in": 100}, previous={"refresh_token": "keep"}
    )
    assert tokens["refresh_token"] == "keep"
    assert tokens["expires_at"] > time.time()


def test_access_token_refreshes_when_expired(monkeypatch):
    monkeypatch.setenv("YOTO_CLIENT_ID", "CID")
    auth.save_tokens({"access_token": "stale", "refresh_token": "r", "expires_at": 0})
    monkeypatch.setattr(
        auth, "_post_token", lambda payload: {"access_token": "fresh", "expires_in": 3600}
    )
    assert auth.access_token() == "fresh"


def test_access_token_reuses_a_live_token(monkeypatch):
    monkeypatch.setenv("YOTO_CLIENT_ID", "CID")
    auth.save_tokens(
        {"access_token": "good", "refresh_token": "r", "expires_at": int(time.time()) + 999}
    )
    monkeypatch.setattr(auth, "_post_token", lambda payload: pytest.fail("refreshed"))
    assert auth.access_token() == "good"


def test_access_token_without_login_is_an_error(monkeypatch):
    monkeypatch.setenv("YOTO_CLIENT_ID", "CID")
    with pytest.raises(auth.AuthError, match="not logged in"):
        auth.access_token()


def test_access_token_without_client_id_is_an_error():
    auth.save_tokens({"access_token": "a", "refresh_token": "r", "expires_at": 0})
    with pytest.raises(auth.AuthError, match="client id"):
        auth.access_token()


def test_scopes_request_content_view_explicitly():
    # The API rejects reads with only user:content:manage, despite the docs.
    assert "user:content:view" in config.SCOPES
