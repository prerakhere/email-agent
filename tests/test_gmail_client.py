import base64
from types import SimpleNamespace
from unittest.mock import MagicMock

from agent.gmail_client import GmailClient, message_to_email


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def make_message(
    mid="m1",
    headers=None,
    body_parts=None,
    mime="text/plain",
    data="hello",
    labels=None,
) -> dict:
    headers = headers or [
        {"name": "From", "value": "Shop <deals@shop.com>"},
        {"name": "Subject", "value": "50% off"},
    ]
    payload = {"headers": headers, "mimeType": mime, "body": {"data": b64(data)}}
    if body_parts is not None:
        payload = {
            "headers": headers,
            "mimeType": "multipart/alternative",
            "parts": body_parts,
        }
    return {
        "id": mid,
        "threadId": f"t-{mid}",
        "labelIds": labels or ["INBOX"],
        "payload": payload,
    }


def test_message_to_email_reads_headers_ids_and_labels():
    msg = make_message(labels=["INBOX", "UNREAD", "STARRED"])
    email = message_to_email(msg)
    assert email.id == "m1"
    assert email.thread_id == "t-m1"
    assert email.sender == "Shop <deals@shop.com>"
    assert email.subject == "50% off"
    assert email.body_preview == "hello"
    assert email.is_starred and email.is_unread
    assert email.list_unsubscribe is False


def test_header_names_are_matched_case_insensitively_and_unsubscribe_detected():
    headers = [
        {"name": "from", "value": "a@b.com"},
        {"name": "SUBJECT", "value": "hi"},
        {"name": "List-Unsubscribe", "value": "<mailto:u@b.com>"},
    ]
    email = message_to_email(make_message(headers=headers))
    assert email.sender == "a@b.com"
    assert email.subject == "hi"
    assert email.list_unsubscribe is True


def test_missing_subject_becomes_empty_string():
    email = message_to_email(
        make_message(headers=[{"name": "From", "value": "a@b.com"}])
    )
    assert email.subject == ""


def test_plain_text_part_is_preferred_in_multipart_messages():
    parts = [
        {"mimeType": "text/html", "body": {"data": b64("<p>html version</p>")}},
        {"mimeType": "text/plain", "body": {"data": b64("plain version")}},
    ]
    assert (
        message_to_email(make_message(body_parts=parts)).body_preview == "plain version"
    )


def test_nested_multipart_body_is_found():
    inner = {
        "mimeType": "multipart/alternative",
        "parts": [{"mimeType": "text/plain", "body": {"data": b64("deep text")}}],
    }
    email = message_to_email(make_message(body_parts=[inner]))
    assert email.body_preview == "deep text"


def test_html_only_body_has_tags_stripped():
    parts = [
        {"mimeType": "text/html", "body": {"data": b64("<p>Pay <b>Rs 500</b></p>")}}
    ]
    assert message_to_email(make_message(body_parts=parts)).body_preview == "Pay Rs 500"


def test_message_without_body_gives_empty_preview():
    msg = make_message(body_parts=[{"mimeType": "image/png", "body": {"size": 5}}])
    assert message_to_email(msg).body_preview == ""


def test_very_long_body_is_capped():
    assert len(message_to_email(make_message(data="x" * 10_000)).body_preview) == 2000


# ---- GmailClient with a fake Google service (no network) ----


def fake_service(list_pages: list[dict], messages: dict[str, dict], labels=None):
    service = MagicMock()
    msgs = service.users.return_value.messages.return_value
    msgs.list.return_value.execute.side_effect = list_pages
    msgs.get.side_effect = lambda **kw: SimpleNamespace(
        execute=lambda: messages[kw["id"]]
    )
    service.users.return_value.labels.return_value.list.return_value.execute.return_value = {
        "labels": labels or []
    }
    return service


def test_fetch_recent_builds_inbox_query_and_returns_emails():
    service = fake_service(
        [{"messages": [{"id": "a"}, {"id": "b"}]}],
        {"a": make_message("a"), "b": make_message("b")},
    )
    emails = GmailClient(service).fetch_recent(days=3)
    assert [e.id for e in emails] == ["a", "b"]
    msgs = service.users.return_value.messages.return_value
    assert msgs.list.call_args.kwargs["q"] == "in:inbox newer_than:3d"
    assert msgs.list.call_args.kwargs["userId"] == "me"
    assert msgs.get.call_args.kwargs["format"] == "full"


def test_fetch_recent_follows_pagination():
    service = fake_service(
        [
            {"messages": [{"id": "a"}], "nextPageToken": "p2"},
            {"messages": [{"id": "b"}]},
        ],
        {"a": make_message("a"), "b": make_message("b")},
    )
    assert [e.id for e in GmailClient(service).fetch_recent(days=1)] == ["a", "b"]


def test_fetch_recent_stops_at_max_results():
    service = fake_service(
        [{"messages": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}],
        {k: make_message(k) for k in "abc"},
    )
    assert [e.id for e in GmailClient(service).fetch_recent(days=1, max_results=2)] == [
        "a",
        "b",
    ]


def test_fetch_recent_with_empty_inbox_returns_empty_list():
    service = fake_service([{}], {})
    assert GmailClient(service).fetch_recent(days=1) == []


def test_list_label_names_returns_only_user_labels_sorted():
    labels = [
        {"name": "INBOX", "type": "system"},
        {"name": "Newsletters", "type": "user"},
        {"name": "Finances", "type": "user"},
    ]
    service = fake_service([], {}, labels=labels)
    assert GmailClient(service).list_label_names() == ["Finances", "Newsletters"]


def test_label_ids_by_name_maps_user_labels_only():
    labels = [
        {"id": "INBOX", "name": "INBOX", "type": "system"},
        {"id": "Label_1", "name": "Newsletters", "type": "user"},
        {"id": "Label_2", "name": "Finances/Bank", "type": "user"},
    ]
    service = fake_service([], {}, labels=labels)
    assert GmailClient(service).label_ids_by_name() == {
        "Newsletters": "Label_1",
        "Finances/Bank": "Label_2",
    }


def sender_message(mid: str, sender: str | None) -> dict:
    headers = [] if sender is None else [{"name": "From", "value": sender}]
    return {"id": mid, "payload": {"headers": headers}}


def test_fetch_senders_returns_from_headers_using_metadata_only():
    service = fake_service(
        [{"messages": [{"id": "a"}, {"id": "b"}]}],
        {"a": sender_message("a", "X <x@a.com>"), "b": sender_message("b", "y@b.com")},
    )
    senders = GmailClient(service).fetch_senders("Label_1")
    assert senders == ["X <x@a.com>", "y@b.com"]
    msgs = service.users.return_value.messages.return_value
    assert msgs.list.call_args.kwargs["labelIds"] == ["Label_1"]
    assert msgs.get.call_args.kwargs["format"] == "metadata"
    assert msgs.get.call_args.kwargs["metadataHeaders"] == ["From"]


def test_fetch_senders_follows_pagination_and_stops_at_max_results():
    service = fake_service(
        [
            {"messages": [{"id": "a"}, {"id": "b"}], "nextPageToken": "p2"},
            {"messages": [{"id": "c"}]},
        ],
        {k: sender_message(k, f"{k}@x.com") for k in "abc"},
    )
    assert GmailClient(service).fetch_senders("L", max_results=2) == [
        "a@x.com",
        "b@x.com",
    ]


def test_fetch_senders_skips_messages_without_a_from_header():
    service = fake_service(
        [{"messages": [{"id": "a"}, {"id": "b"}]}],
        {"a": sender_message("a", None), "b": sender_message("b", "b@x.com")},
    )
    assert GmailClient(service).fetch_senders("L") == ["b@x.com"]


def test_fetch_senders_for_an_empty_label_returns_empty_list():
    assert GmailClient(fake_service([{}], {})).fetch_senders("L") == []
