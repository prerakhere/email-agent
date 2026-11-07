from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from agent.execute import execute_run
from agent.schemas import Bill, Category, Classification, Email, Proposal


def make_state(with_bill=True):
    email = Email(
        id="m1", thread_id="t1", sender="Bank <s@bank.com>", subject="Statement"
    )
    classification = Classification(
        category=Category.BILLS, confidence=0.9, reason="r", source="llm"
    )
    proposal = Proposal(
        email_id="m1",
        sender=email.sender,
        subject=email.subject,
        category=Category.BILLS,
        label="Finances/Statements, Receipts",
        confidence=0.9,
        reason="r",
        source="llm",
    )
    bill = Bill(
        vendor="HDFC Bank",
        amount=Decimal("5633.00"),
        currency="INR",
        due_date=date(2026, 11, 9),
        confidence=0.9,
    )
    return {
        "emails": [email],
        "classifications": {"m1": classification},
        "proposals": [proposal],
        "bills": {"m1": bill} if with_bill else {},
    }


def make_fakes():
    """A sheets fake and a gmail fake that record the order of their calls in one list."""
    order: list[str] = []
    sheets = MagicMock()
    sheets.log_bills.side_effect = lambda items: (order.append("sheet"), ["m1"])[1]
    gmail = MagicMock()
    gmail.ensure_label.side_effect = lambda name: (order.append("label"), "L1")[1]
    return gmail, sheets, order


def test_the_sheet_is_written_before_any_label_is_touched():
    gmail, sheets, order = make_fakes()
    execute_run(make_state(), gmail, sheets, label=True)
    assert order == ["sheet", "label"]


def test_a_failed_sheet_write_stops_labelling():
    gmail, sheets, _order = make_fakes()
    sheets.log_bills.side_effect = RuntimeError("sheet down")
    with pytest.raises(RuntimeError, match="sheet down"):
        execute_run(make_state(), gmail, sheets, label=True)
    gmail.ensure_label.assert_not_called()
    gmail.add_label.assert_not_called()


def test_without_labelling_only_the_sheet_is_written():
    gmail, sheets, order = make_fakes()
    outcome = execute_run(make_state(), gmail, sheets, label=False)
    assert order == ["sheet"]
    gmail.ensure_label.assert_not_called()
    gmail.add_label.assert_not_called()
    assert outcome.labelled is None
    assert outcome.rows_added == ["m1"]


def test_no_bills_means_the_sheet_is_not_called_at_all():
    gmail, sheets, order = make_fakes()
    outcome = execute_run(make_state(with_bill=False), gmail, sheets, label=True)
    sheets.log_bills.assert_not_called()
    assert outcome.rows_added == []
    assert order == ["label"]


def test_labelling_uses_keep_in_inbox_by_default_and_reports_what_it_did():
    gmail, sheets, _order = make_fakes()
    outcome = execute_run(make_state(), gmail, sheets, label=True)
    gmail.add_label.assert_called_once_with("m1", "L1")
    gmail.move_to_label.assert_not_called()
    assert [p.email_id for p in outcome.labelled.moved] == ["m1"]
    assert outcome.labelled.keep_in_inbox is True


def test_moving_out_of_the_inbox_is_passed_through():
    gmail, sheets, _order = make_fakes()
    outcome = execute_run(make_state(), gmail, sheets, label=True, keep_in_inbox=False)
    gmail.move_to_label.assert_called_once_with("m1", "L1")
    assert outcome.labelled.keep_in_inbox is False


def test_without_a_sheets_client_bills_are_not_logged_but_labelling_still_runs():
    gmail, _, order = make_fakes()
    outcome = execute_run(make_state(), gmail, None, label=True)
    assert outcome.rows_added == []
    assert order == ["label"]
