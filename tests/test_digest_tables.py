from datetime import UTC, date, datetime
from decimal import Decimal

from langchain_core.runnables import RunnableLambda

from agent.digest import build_digest
from agent.digest_config import DigestConfig, DigestSection
from agent.nodes.transactions import Transaction
from agent.schemas import Bill, Category, Classification, Email

NOW = datetime(2026, 11, 8, 3, 0, tzinfo=UTC)


def exploding(_request):
    raise AssertionError("table sections must not call the model")


def email(mid, subject="s", sender="Bank <b@x.com>"):
    return Email(
        id=mid, thread_id=f"t-{mid}", sender=sender, subject=subject, body_preview="b"
    )


def classify(pairs):
    emails = [e for e, _ in pairs]
    return emails, {
        e.id: Classification(category=c, confidence=1.0, reason="r", source="llm")
        for e, c in pairs
    }


def bill(vendor="HDFC Bank", amount="5633.00", due=date(2026, 11, 9), currency="INR"):
    return Bill(
        vendor=vendor,
        amount=Decimal(amount),
        currency=currency,
        due_date=due,
        confidence=0.9,
    )


def tx(mid, amount="50.00", payee=None, via="UPI", direction="debit", currency="INR"):
    return Transaction(
        email_id=mid,
        amount=Decimal(amount),
        currency=currency,
        payee=payee,
        via=via,
        direction=direction,
    )


BILLS_CONFIG = DigestConfig(
    sections=[
        DigestSection(
            title="Bills", categories=["bills", "receipts"], mode="table", table="bills"
        )
    ]
)
TX_CONFIG = DigestConfig(
    sections=[
        DigestSection(
            title="Spend",
            categories=["transactions"],
            mode="table",
            table="transactions",
            max_items=3,
        )
    ]
)


def run(pairs, config, bills=None, transactions=None, now=NOW):
    emails, classes = classify(pairs)
    return build_digest(
        emails,
        classes,
        config,
        RunnableLambda(exploding),
        RunnableLambda(exploding),
        bills=bills or {},
        transactions=transactions or {},
        now=now,
    )


def test_a_bills_table_has_a_row_per_extracted_bill_and_no_model_call():
    pairs = [(email("1"), Category.BILLS), (email("2"), Category.RECEIPTS)]
    bills = {
        "1": bill("HDFC Bank", "5633.00", date(2026, 11, 9)),
        "2": bill("Amazon.in", "85004.00", None),
    }
    section = run(pairs, BILLS_CONFIG, bills=bills).sections[0]
    assert section.mode == "table" and section.count == 2
    table = section.table
    assert table.columns == ["Type", "Biller", "Amount", "Due"]
    assert [r.cells for r in table.rows] == [
        ["bill", "HDFC Bank", "INR 5,633.00", "2026-11-09"],
        ["receipt", "Amazon.in", "INR 85,004.00", "-"],
    ]


def test_bills_are_ordered_by_the_soonest_due_date_and_undated_ones_come_last():
    pairs = [(email(str(i)), Category.BILLS) for i in range(3)]
    bills = {
        "0": bill("Later", due=date(2026, 12, 20)),
        "1": bill("NoDate", due=None),
        "2": bill("Soon", due=date(2026, 11, 9)),
    }
    rows = run(pairs, BILLS_CONFIG, bills=bills).sections[0].table.rows
    assert [r.cells[1] for r in rows] == ["Soon", "Later", "NoDate"]


def test_a_bill_due_within_three_days_is_highlighted_and_later_ones_are_not():
    pairs = [(email("1"), Category.BILLS), (email("2"), Category.BILLS)]
    bills = {"1": bill(due=date(2026, 11, 10)), "2": bill(due=date(2026, 11, 30))}
    rows = run(pairs, BILLS_CONFIG, bills=bills).sections[0].table.rows
    assert [r.highlight for r in rows] == [True, False]
    without_clock = (
        run(pairs, BILLS_CONFIG, bills=bills, now=None).sections[0].table.rows
    )
    assert not any(r.highlight for r in without_clock)


def test_the_bills_line_totals_bills_and_receipts_separately_by_currency():
    pairs = [
        (email("1"), Category.BILLS),
        (email("2"), Category.BILLS),
        (email("3"), Category.RECEIPTS),
    ]
    bills = {
        "1": bill(amount="1000.00"),
        "2": bill(amount="500.50"),
        "3": bill("Shop", amount="20.00", currency="USD"),
    }
    line = run(pairs, BILLS_CONFIG, bills=bills).sections[0].table.summary
    assert "2 bills" in line and "INR 1,500.50" in line
    assert "1 receipt" in line and "USD 20.00" in line


def test_bill_like_mail_with_no_extracted_amount_is_listed_below_not_in_the_table():
    pairs = [
        (email("1"), Category.BILLS),
        (email("2", "Offer for you"), Category.BILLS),
    ]
    table = run(pairs, BILLS_CONFIG, bills={"1": bill()}).sections[0].table
    assert len(table.rows) == 1
    assert [(r.email_id, r.subject) for r in table.unlisted] == [("2", "Offer for you")]


def test_a_table_section_with_nothing_extracted_still_lists_its_mail():
    section = run([(email("1", "Reminder"), Category.BILLS)], BILLS_CONFIG).sections[0]
    assert section.table.rows == [] and len(section.table.unlisted) == 1
    assert section.table.summary  # says something sensible, not an empty string


def test_a_transactions_table_shows_amount_how_paid_and_payee_with_credits_marked():
    pairs = [(email("1"), Category.TRANSACTIONS), (email("2"), Category.TRANSACTIONS)]
    found = {
        "1": tx("1", "450.00", "Cafe Blue", "UPI", "debit"),
        "2": tx("2", "200.00", None, "credit card", "credit"),
    }
    table = run(pairs, TX_CONFIG, transactions=found).sections[0].table
    assert table.columns == ["Amount", "Via", "To"]
    assert [r.cells for r in table.rows] == [
        ["INR 450.00", "UPI", "Cafe Blue"],
        ["+INR 200.00", "credit card", "-"],
    ]


def test_the_transactions_line_gives_count_spend_how_paid_largest_and_money_in():
    pairs = [(email(str(i)), Category.TRANSACTIONS) for i in range(4)]
    found = {
        "0": tx("0", "100.00", via="UPI"),
        "1": tx("1", "600.00", via="UPI"),
        "2": tx("2", "40.00", via="credit card"),
        "3": tx("3", "200.00", direction="credit"),
    }
    line = run(pairs, TX_CONFIG, transactions=found).sections[0].table.summary
    assert "4 transactions" in line
    assert "spent INR 740.00" in line
    assert "UPI 2" in line and "credit card 1" in line
    assert "largest INR 600.00" in line
    assert "received INR 200.00" in line


def test_only_max_items_rows_are_shown_but_the_totals_cover_every_transaction():
    pairs = [(email(str(i)), Category.TRANSACTIONS) for i in range(5)]
    found = {str(i): tx(str(i), "10.00") for i in range(5)}
    table = run(pairs, TX_CONFIG, transactions=found).sections[0].table
    assert len(table.rows) == 3 and table.omitted == 2
    assert "5 transactions" in table.summary and "spent INR 50.00" in table.summary


def test_transaction_alerts_with_no_amount_are_listed_not_counted():
    pairs = [
        (email("1"), Category.TRANSACTIONS),
        (email("2", "odd alert"), Category.TRANSACTIONS),
    ]
    table = run(pairs, TX_CONFIG, transactions={"1": tx("1")}).sections[0].table
    assert len(table.rows) == 1 and [r.email_id for r in table.unlisted] == ["2"]
    assert "1 transaction" in table.summary
