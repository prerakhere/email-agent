"""Phase 0: validate Google access end-to-end with the user's real account.

Run once interactively (opens a browser for consent):  uv run python scripts/phase0_check.py
Never prints tokens or message bodies; only subjects/senders of 5 messages.

Checks: OAuth login -> token saved -> token refresh without browser -> list mail ->
create/apply/remove/delete a test label -> append and clear a Sheet row.
"""

import os
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
CREDENTIALS = ROOT / "credentials.json"
TOKEN = ROOT / "token.json"
SHEET_ID = os.environ.get("SHEET_ID", "")
TEST_LABEL = "Agent/_phase0_test"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",  # read, label, move (no permanent delete)
    "https://www.googleapis.com/auth/gmail.send",  # digest email
    "https://www.googleapis.com/auth/spreadsheets",  # bills sheet
]


def step(msg: str) -> None:
    print(f"\n==> {msg}")


def get_credentials() -> Credentials:
    creds = None
    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if creds and creds.refresh_token:
        # Always refresh (don't trust local expiry): catches revoked/expired tokens early.
        try:
            creds.refresh(Request())
        except RefreshError:
            print("Stored token is revoked/expired; starting a fresh login.")
            creds = None
    if not creds:
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS), SCOPES)
        creds = flow.run_local_server(port=0)
    TOKEN.write_text(creds.to_json())
    TOKEN.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600
    return creds


def check_headless_refresh(creds: Credentials) -> None:
    step("Headless refresh (what the Azure Function will do each run)")
    if not creds.refresh_token:
        sys.exit(
            "FAIL: no refresh token. Re-run after revoking app access, or check consent screen."
        )
    creds.refresh(Request())
    print("OK: access token refreshed using the refresh token, no browser needed.")


def check_gmail(creds: Credentials) -> None:
    gmail = build("gmail", "v1", credentials=creds)

    step("List 5 recent inbox messages (subject / from only)")
    res = (
        gmail.users()
        .messages()
        .list(userId="me", labelIds=["INBOX"], maxResults=5)
        .execute()
    )
    msgs = res.get("messages", [])
    for m in msgs:
        full = (
            gmail.users()
            .messages()
            .get(
                userId="me",
                id=m["id"],
                format="metadata",
                metadataHeaders=["Subject", "From"],
            )
            .execute()
        )
        h = {x["name"]: x["value"] for x in full["payload"]["headers"]}
        print(f"- {h.get('From', '?')[:40]:40} | {h.get('Subject', '?')[:60]}")
    if not msgs:
        sys.exit("FAIL: inbox returned no messages.")

    step(
        f"Create label {TEST_LABEL!r}, apply to first message, remove it, delete label"
    )
    existing = gmail.users().labels().list(userId="me").execute()["labels"]
    label = next((x for x in existing if x["name"] == TEST_LABEL), None)
    if not label:
        label = (
            gmail.users()
            .labels()
            .create(userId="me", body={"name": TEST_LABEL})
            .execute()
        )
    lid, mid = label["id"], msgs[0]["id"]
    gmail.users().messages().modify(
        userId="me", id=mid, body={"addLabelIds": [lid]}
    ).execute()
    got = gmail.users().messages().get(userId="me", id=mid, format="minimal").execute()
    assert lid in got["labelIds"], "label was not applied"
    print("OK: label applied and verified.")
    gmail.users().messages().modify(
        userId="me", id=mid, body={"removeLabelIds": [lid]}
    ).execute()
    gmail.users().labels().delete(userId="me", id=lid).execute()
    print("OK: label removed from message and deleted. Inbox state restored.")

    step("Existing user labels (names only, to seed rules later)")
    names = sorted(x["name"] for x in existing if x["type"] == "user")
    print(", ".join(names) or "(none)")


def check_sheets(creds: Credentials) -> None:
    step("Append a test row to the Bills sheet, then clear it")
    sheets = build("sheets", "v4", credentials=creds)
    row = [datetime.now(UTC).isoformat(), "PHASE0 TEST", "0", "INR", "", "", "", "1.0"]
    res = (
        sheets.spreadsheets()
        .values()
        .append(
            spreadsheetId=SHEET_ID,
            range="A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        )
        .execute()
    )
    updated = res["updates"]["updatedRange"]
    print(f"OK: appended at {updated}")
    sheets.spreadsheets().values().clear(
        spreadsheetId=SHEET_ID, range=updated, body={}
    ).execute()
    print("OK: test row cleared.")


def main() -> None:
    if not CREDENTIALS.exists():
        sys.exit(f"Missing {CREDENTIALS.name}; see setup steps.")
    if not SHEET_ID:
        sys.exit("Set SHEET_ID in .env (see .env.example).")
    creds = get_credentials()
    print("OK: authenticated; token.json saved (chmod 600, gitignored).")
    check_headless_refresh(creds)
    check_gmail(creds)
    check_sheets(creds)
    print("\nPHASE 0 (direct Google API path): ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
