import json

import pytest
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials

from agent.auth import (
    SCOPES,
    SignInExpiredError,
    credentials_from_env,
    refreshed_credentials,
)

TOKEN = {
    "client_id": "client-id-123",
    "client_secret": "client-secret-456",
    "refresh_token": "refresh-token-789",
    "token_uri": "https://oauth2.googleapis.com/token",
}


def env(**overrides):
    return {"GOOGLE_TOKEN_JSON": json.dumps(TOKEN), **overrides}


def test_credentials_are_built_from_the_token_setting_with_our_three_scopes():
    creds = credentials_from_env(env())
    assert isinstance(creds, Credentials)
    assert creds.refresh_token == "refresh-token-789"
    assert sorted(s.rsplit("/", 1)[-1] for s in SCOPES) == [
        "gmail.modify",
        "gmail.send",
        "spreadsheets",
    ]
    assert sorted(creds.scopes) == sorted(SCOPES)


def test_a_missing_setting_is_named_in_the_error():
    with pytest.raises(ValueError, match="GOOGLE_TOKEN_JSON"):
        credentials_from_env({})


def test_a_setting_that_is_not_json_gives_a_clear_error_without_echoing_it():
    with pytest.raises(ValueError, match="not valid JSON") as caught:
        credentials_from_env({"GOOGLE_TOKEN_JSON": "oops-secret-text {"})
    assert "oops-secret-text" not in str(caught.value)


def test_a_token_without_a_refresh_token_is_rejected_without_echoing_secrets():
    broken = {k: v for k, v in TOKEN.items() if k != "refresh_token"}
    with pytest.raises(ValueError, match="refresh token") as caught:
        credentials_from_env({"GOOGLE_TOKEN_JSON": json.dumps(broken)})
    assert "client-secret-456" not in str(caught.value)


def test_refreshing_fetches_a_fresh_access_token_with_no_browser(monkeypatch):
    def fake_refresh(self, request):
        self.token = "fresh-access-token"

    monkeypatch.setattr(Credentials, "refresh", fake_refresh)
    creds = refreshed_credentials(env())
    assert creds.token == "fresh-access-token"


def test_an_expired_or_revoked_sign_in_has_its_own_clear_error(monkeypatch):
    def fake_refresh(self, request):
        raise RefreshError("invalid_grant: Token has been expired or revoked.")

    monkeypatch.setattr(Credentials, "refresh", fake_refresh)
    with pytest.raises(SignInExpiredError, match="sign in again") as caught:
        refreshed_credentials(env())
    assert "refresh-token-789" not in str(caught.value)
    assert "client-secret-456" not in str(caught.value)
