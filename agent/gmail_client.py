"""Thin wrapper around the Gmail API.

The Google `service` object is injected so tests can pass a fake and never touch a real account.
Nothing here prints or logs message content.
"""

import base64
from datetime import UTC, datetime
from html.parser import HTMLParser

from agent.schemas import Email

BODY_PREVIEW_CHARS = 2000
PAGE_SIZE = 100
AGENT_PREFIX = "Agent/"
# Gmail rate-limits bursts of message reads (403/429). Google's client retries with backoff
# when execute() is given num_retries, so a large fetch slows down instead of crashing.
READ_RETRIES = 5


class _TextExtractor(HTMLParser):
    """Collects visible text from HTML, skipping <script>/<style>."""

    def __init__(self) -> None:
        super().__init__()
        self.chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.chunks.append(data)


def _strip_html(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return " ".join(" ".join(parser.chunks).split())


def _decode(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _find_part(part: dict, mime: str) -> str | None:
    """Depth-first search for the first part of `mime` type that has body data."""
    if part.get("mimeType") == mime and part.get("body", {}).get("data"):
        return _decode(part["body"]["data"])
    for child in part.get("parts", []):
        found = _find_part(child, mime)
        if found is not None:
            return found
    return None


def _extract_body(payload: dict) -> str:
    plain = _find_part(payload, "text/plain")
    if plain is not None:
        return plain.strip()[:BODY_PREVIEW_CHARS]
    html = _find_part(payload, "text/html")
    if html is not None:
        return _strip_html(html)[:BODY_PREVIEW_CHARS]
    return ""


def _received_at(message: dict) -> datetime | None:
    """Gmail's own arrival time (internalDate, milliseconds since epoch), as UTC."""
    millis = message.get("internalDate")
    if millis is None:
        return None
    return datetime.fromtimestamp(int(millis) / 1000, tz=UTC)


def message_to_email(message: dict) -> Email:
    """Convert a Gmail API `format=full` message dict into our Email model."""
    payload = message.get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
    return Email(
        id=message["id"],
        thread_id=message["threadId"],
        sender=headers.get("from", ""),
        subject=headers.get("subject", ""),
        body_preview=_extract_body(payload),
        list_unsubscribe="list-unsubscribe" in headers,
        label_ids=message.get("labelIds", []),
        received_at=_received_at(message),
    )


class GmailClient:
    def __init__(self, service) -> None:
        self._service = service

    def list_label_names(self) -> list[str]:
        response = self._service.users().labels().list(userId="me").execute()
        return sorted(
            x["name"] for x in response.get("labels", []) if x["type"] == "user"
        )

    def label_ids_by_name(self) -> dict[str, str]:
        response = self._service.users().labels().list(userId="me").execute()
        return {
            x["name"]: x["id"]
            for x in response.get("labels", [])
            if x["type"] == "user"
        }

    def ensure_label(self, name: str) -> str:
        """Id of the label `name`; creates it only if missing AND it lives under Agent/.

        Refusing other names is the code-level guard for "the agent never invents labels".
        """
        for existing, label_id in self.label_ids_by_name().items():
            if existing.lower() == name.lower():
                return label_id
        if not name.startswith(AGENT_PREFIX):
            raise ValueError(
                f"Refusing to create label {name!r}: only {AGENT_PREFIX}* is allowed"
            )
        created = (
            self._service.users()
            .labels()
            .create(
                userId="me",
                body={
                    "name": name,
                    "labelListVisibility": "labelShow",
                    "messageListVisibility": "show",
                },
            )
            .execute()
        )
        return created["id"]

    def add_label(self, email_id: str, label_id: str) -> None:
        """Label one message and change nothing else: it stays in the inbox, unread state intact."""
        self._service.users().messages().modify(
            userId="me", id=email_id, body={"addLabelIds": [label_id]}
        ).execute()

    def move_to_label(self, email_id: str, label_id: str) -> None:
        """File one message: add `label_id` and remove INBOX in a single call.

        Mechanics only. Never touches TRASH, so mail is labelled, never deleted. Which mail
        may be moved at all (not Important/starred) is decided by the caller.
        """
        self._service.users().messages().modify(
            userId="me",
            id=email_id,
            body={"addLabelIds": [label_id], "removeLabelIds": ["INBOX"]},
        ).execute()

    def _list_message_ids(self, max_results: int, **query) -> list[str]:
        """Message ids matching `query` (messages.list kwargs), following pagination."""
        ids: list[str] = []
        page_token = None
        while len(ids) < max_results:
            response = (
                self._service.users()
                .messages()
                .list(
                    userId="me",
                    maxResults=min(PAGE_SIZE, max_results - len(ids)),
                    pageToken=page_token,
                    **query,
                )
                .execute(num_retries=READ_RETRIES)
            )
            ids.extend(m["id"] for m in response.get("messages", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return ids[:max_results]

    def fetch_senders(self, label_id: str, max_results: int = 200) -> list[str]:
        """`From` headers of mail in one label. Metadata only: no bodies are fetched."""
        senders = []
        for mid in self._list_message_ids(max_results, labelIds=[label_id]):
            message = (
                self._service.users()
                .messages()
                .get(userId="me", id=mid, format="metadata", metadataHeaders=["From"])
                .execute(num_retries=READ_RETRIES)
            )
            headers = message.get("payload", {}).get("headers", [])
            sender = next(
                (h["value"] for h in headers if h["name"].lower() == "from"), None
            )
            if sender:
                senders.append(sender)
        return senders

    def _get_emails(self, ids: list[str]) -> list[Email]:
        return [
            message_to_email(
                self._service.users()
                .messages()
                .get(userId="me", id=mid, format="full")
                .execute(num_retries=READ_RETRIES)
            )
            for mid in ids
        ]

    def fetch_recent(self, days: int, max_results: int = 100) -> list[Email]:
        """Inbox mail from the last `days` days, newest first, at most `max_results`."""
        ids = self._list_message_ids(max_results, q=f"in:inbox newer_than:{days}d")
        return self._get_emails(ids[:max_results])

    def fetch_since(self, since: datetime, max_results: int = 500) -> list[Email]:
        """Every message that arrived after `since` (UTC), wherever it is filed.

        Not limited to the inbox: mail may already have been labelled and moved out. Mail you
        sent and drafts are excluded because they never belong in a digest. `after:` takes an
        exact epoch second, unlike `newer_than:` which only counts whole days.
        """
        query = f"after:{int(since.timestamp())} -in:sent -in:drafts"
        ids = self._list_message_ids(max_results, q=query)
        return self._get_emails(ids[:max_results])
