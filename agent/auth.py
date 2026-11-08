"""Google sign-in for the unattended run: built from ONE setting, no files, no browser.

GOOGLE_TOKEN_JSON holds the authorized-user JSON (client id and secret plus the long-lived refresh
token). Each run loads it and exchanges the refresh token for a fresh access token in memory; Google
does not rotate the refresh token, so nothing is ever written back.

Error messages deliberately never include the setting's contents: they end up in logs.
"""

import json
from collections.abc import Mapping

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/spreadsheets",
]


class SignInExpiredError(RuntimeError):
    """Google rejected the stored refresh token (expired, revoked, or the password changed)."""


def credentials_from_env(env: Mapping[str, str]) -> Credentials:
    raw = env.get("GOOGLE_TOKEN_JSON")
    if not raw:
        raise ValueError("Missing setting: GOOGLE_TOKEN_JSON")
    try:
        info = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("GOOGLE_TOKEN_JSON is not valid JSON") from None
    if not isinstance(info, dict) or not info.get("refresh_token"):
        raise ValueError("GOOGLE_TOKEN_JSON has no refresh token: sign in again")
    try:
        return Credentials.from_authorized_user_info(info, SCOPES)
    except ValueError:
        raise ValueError("GOOGLE_TOKEN_JSON is missing required fields") from None


def refreshed_credentials(env: Mapping[str, str]) -> Credentials:
    """Credentials with a fresh access token, ready to hand to the Google API clients."""
    creds = credentials_from_env(env)
    try:
        creds.refresh(Request())
    except RefreshError:
        raise SignInExpiredError(
            "Google sign-in expired or was revoked: sign in again and update GOOGLE_TOKEN_JSON"
        ) from None
    return creds
