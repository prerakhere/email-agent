import base64
import email
from email import policy
from unittest.mock import MagicMock

from agent.gmail_client import GmailClient


def fake_service(address="me@gmail.com"):
    service = MagicMock()
    users = service.users.return_value
    users.getProfile.return_value.execute.return_value = {"emailAddress": address}
    users.messages.return_value.send.return_value.execute.return_value = {
        "id": "sent-1"
    }
    return service


def sent_message(service):
    """The MIME message that was handed to Gmail, parsed back."""
    send = service.users.return_value.messages.return_value.send
    raw = send.call_args.kwargs["body"]["raw"]
    padded = raw + "=" * (-len(raw) % 4)
    return email.message_from_bytes(
        base64.urlsafe_b64decode(padded), policy=policy.default
    )


def test_the_digest_is_sent_to_the_users_own_address_only():
    service = fake_service("owner@example.com")
    GmailClient(service).send_to_self("Subject", "plain", "<p>html</p>")
    message = sent_message(service)
    assert (
        message["To"] == "owner@example.com" and message["From"] == "owner@example.com"
    )
    assert message["Cc"] is None and message["Bcc"] is None


def test_the_message_has_a_plain_text_and_an_html_version():
    service = fake_service()
    GmailClient(service).send_to_self("Inbox digest", "plain body", "<p>html body</p>")
    message = sent_message(service)
    assert message["Subject"] == "Inbox digest"
    assert (
        message.get_body(preferencelist=("plain",)).get_content().strip()
        == "plain body"
    )
    assert (
        message.get_body(preferencelist=("html",)).get_content().strip()
        == "<p>html body</p>"
    )


def test_non_ascii_text_survives():
    service = fake_service()
    GmailClient(service).send_to_self("Digest – ₹ 5,633", "Crème ₹", "<p>₹</p>")
    message = sent_message(service)
    assert message["Subject"] == "Digest – ₹ 5,633"
    assert "₹" in message.get_body(preferencelist=("plain",)).get_content()


def test_a_newline_in_the_subject_cannot_add_a_header():
    service = fake_service()
    GmailClient(service).send_to_self("Hi\nBcc: evil@example.com", "t", "<p>h</p>")
    message = sent_message(service)
    assert message["Bcc"] is None
    assert "evil@example.com" not in message["To"]
    assert message["Subject"] == "Hi Bcc: evil@example.com"


def test_the_message_id_is_returned_and_sending_is_not_retried():
    service = fake_service()
    assert GmailClient(service).send_to_self("s", "t", "<p>h</p>") == "sent-1"
    send = service.users.return_value.messages.return_value.send
    send.return_value.execute.assert_called_once_with()  # a retry could deliver it twice
    assert send.call_args.kwargs["userId"] == "me"
