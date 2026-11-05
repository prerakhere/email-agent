"""Thin wrapper around the Gmail API.

The Google `service` object is injected so tests can pass a fake and never touch a real account.
Nothing here prints or logs message content.
"""

import base64
from html.parser import HTMLParser

from agent.schemas import Email

BODY_PREVIEW_CHARS = 2000
PAGE_SIZE = 100


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
                .execute()
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
                .execute()
            )
            headers = message.get("payload", {}).get("headers", [])
            sender = next(
                (h["value"] for h in headers if h["name"].lower() == "from"), None
            )
            if sender:
                senders.append(sender)
        return senders

    def fetch_recent(self, days: int, max_results: int = 100) -> list[Email]:
        """Inbox mail from the last `days` days, newest first, at most `max_results`."""
        ids = self._list_message_ids(max_results, q=f"in:inbox newer_than:{days}d")
        return [
            message_to_email(
                self._service.users()
                .messages()
                .get(userId="me", id=mid, format="full")
                .execute()
            )
            for mid in ids[:max_results]
        ]
