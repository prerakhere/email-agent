from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from agent.schemas import Bill, Category, Classification, Email


def make_email(**overrides):
    data = {
        "id": "m1",
        "thread_id": "t1",
        "sender": "ByteByteGo <hello@bytebytego.com>",
        "subject": "EP100: Caching",
        "body_preview": "This week we look at caching...",
    }
    data.update(overrides)
    return Email(**data)


def test_email_sender_address_is_extracted_and_lowercased():
    assert make_email().sender_address == "hello@bytebytego.com"
    assert make_email(sender="PLAIN@Example.COM").sender_address == "plain@example.com"


def test_email_sender_domain():
    assert make_email().sender_domain == "bytebytego.com"


def test_email_flags_from_label_ids():
    assert make_email(label_ids=["INBOX", "STARRED"]).is_starred is True
    assert make_email(label_ids=["INBOX"]).is_starred is False
    assert make_email(label_ids=["INBOX", "UNREAD"]).is_unread is True


def test_email_defaults():
    e = make_email()
    assert e.list_unsubscribe is False
    assert e.label_ids == []


def test_classification_confidence_must_be_between_0_and_1():
    with pytest.raises(ValidationError):
        Classification(
            category=Category.BILLS, confidence=1.2, reason="x", source="llm"
        )
    with pytest.raises(ValidationError):
        Classification(
            category=Category.BILLS, confidence=-0.1, reason="x", source="llm"
        )


def test_classification_source_is_restricted():
    with pytest.raises(ValidationError):
        Classification(
            category=Category.BILLS, confidence=0.9, reason="x", source="guess"
        )


def test_category_values_cover_plan():
    names = {c.name for c in Category}
    assert {
        "BILLS",
        "RECEIPTS",
        "NEWSLETTERS",
        "PROMOTIONS",
        "IMPORTANT",
        "NOTIFICATIONS",
        "JOB_ALERTS",
        "NEEDS_REVIEW",
    } <= names


def test_bill_amount_is_decimal_and_positive():
    b = Bill(
        vendor="HDFC Credit Card",
        amount="1234.50",
        currency="INR",
        due_date=date(2026, 11, 20),
        confidence=0.9,
    )
    assert b.amount == Decimal("1234.50")
    with pytest.raises(ValidationError):
        Bill(vendor="x", amount="-5", currency="INR", confidence=0.9)


def test_bill_due_date_optional():
    assert (
        Bill(vendor="x", amount="10", currency="INR", confidence=0.5).due_date is None
    )
