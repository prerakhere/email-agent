from datetime import date
from decimal import Decimal

from agent.apply import ApplyResult
from agent.report import format_apply_report, format_bill_plan, format_table
from agent.schemas import Bill, Category, Email, Proposal


def make_proposal(**kwargs) -> Proposal:
    defaults = {
        "email_id": "1",
        "sender": "Shop <deals@shop.com>",
        "subject": "50% off",
        "category": Category.PROMOTIONS,
        "label": "Agent/Promotions",
        "confidence": 0.9,
        "reason": "sale",
        "source": "llm",
    }
    return Proposal(**{**defaults, **kwargs})


def test_empty_list_says_no_emails():
    assert format_table([]) == "No emails to show."


def test_table_has_header_and_one_row_per_proposal():
    lines = format_table([make_proposal(), make_proposal(email_id="2")]).splitlines()
    assert "Sender" in lines[0] and "Subject" in lines[0] and "Label" in lines[0]
    rows = [line for line in lines if "deals@shop.com" in line]
    assert len(rows) == 2


def test_row_shows_category_label_confidence_and_source():
    table = format_table([make_proposal(confidence=0.857, source="rule")])
    assert "promotions" in table
    assert "Agent/Promotions" in table
    assert "0.86" in table
    assert "rule" in table


def test_long_values_are_truncated_with_an_ellipsis():
    table = format_table([make_proposal(subject="x" * 200)])
    assert "x" * 200 not in table
    assert "…" in table


def test_summary_counts_categories_and_rule_decisions():
    proposals = [
        make_proposal(email_id="1", category=Category.NEWSLETTERS, source="rule"),
        make_proposal(email_id="2", category=Category.NEWSLETTERS, source="rule"),
        make_proposal(email_id="3", category=Category.PROMOTIONS, source="llm"),
    ]
    summary = format_table(proposals).splitlines()[-1]
    assert "3 emails" in summary
    assert "2 decided by rules" in summary
    assert "newsletters=2" in summary
    assert "promotions=1" in summary


def test_apply_report_lists_moves_and_keeps_with_reasons():
    move = make_proposal(email_id="1", subject="Weekly digest", label="Newsletters")
    keep = make_proposal(email_id="2", subject="Your interview")
    result = ApplyResult(planned=[move], skipped=[(keep, "important mail stays")])
    text = format_apply_report(result, dry_run=True)
    assert "MOVE" in text and "Weekly digest" in text and "Newsletters" in text
    assert (
        "KEEP" in text and "Your interview" in text and "important mail stays" in text
    )


def test_apply_report_dry_run_says_nothing_was_changed():
    result = ApplyResult(planned=[make_proposal()])
    text = format_apply_report(result, dry_run=True)
    assert "DRY RUN" in text and "1 would move" in text


def test_apply_report_real_run_says_how_many_were_moved():
    p = make_proposal()
    result = ApplyResult(planned=[p], moved=[p])
    text = format_apply_report(result, dry_run=False)
    assert "1 moved" in text and "DRY RUN" not in text


def test_apply_report_with_nothing_to_do():
    assert "Nothing to move" in format_apply_report(ApplyResult(), dry_run=True)


def test_apply_report_in_keep_mode_says_label_and_that_mail_stays():
    p = make_proposal(label="Newsletters")
    planned = ApplyResult(planned=[p], keep_in_inbox=True)
    text = format_apply_report(planned, dry_run=True)
    assert "LABEL" in text and "MOVE" not in text and "1 would be labelled" in text
    done = ApplyResult(planned=[p], moved=[p], keep_in_inbox=True)
    assert "1 labelled" in format_apply_report(done, dry_run=False)


def bill_item(category=Category.BILLS, confidence=0.9, due=date(2026, 12, 5)):
    email = Email(
        id="m1", thread_id="t1", sender="Example <s@bank.example>", subject="Statement"
    )
    bill = Bill(
        vendor="Example Bank",
        amount=Decimal("12500.50"),
        currency="INR",
        due_date=due,
        confidence=confidence,
    )
    return (email, category, bill)


def test_bill_plan_shows_each_row_with_amount_due_date_and_status():
    text = format_bill_plan([bill_item()])
    assert "bill" in text and "Example Bank" in text
    assert "12,500.50 INR" in text and "due 2026-12-05" in text and "unpaid" in text
    assert "1 row would be added" in text and "DRY RUN" in text


def test_bill_plan_shows_a_receipt_without_a_due_date_and_a_flagged_row():
    receipt = bill_item(Category.RECEIPTS, due=None)
    shaky = bill_item(confidence=0.4)
    text = format_bill_plan([receipt, shaky])
    assert "receipt" in text and "due -" in text and "paid" in text
    assert "check" in text and "2 rows would be added" in text


def test_bill_plan_with_nothing_found_says_so():
    assert format_bill_plan([]) == "No bills or receipts to log."


def test_bill_plan_reports_mails_with_no_readable_amount():
    text = format_bill_plan([bill_item()], missed=2)
    assert "2 bill/receipt mails had no readable amount" in text
    only_missed = format_bill_plan([], missed=1)
    assert "1 bill/receipt mail had no readable amount" in only_missed
