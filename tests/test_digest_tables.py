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
        ["bill", "HDFC Bank", "₹5,633.00", "tomorrow"],
        ["receipt", "Amazon.in", "₹85,004.00", "-"],
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
    assert "2 bills" in line and "₹1,500.50" in line
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
    assert table.columns == ["To", "Via", "Amount"] and table.link_column == 0
    assert [r.cells for r in table.rows] == [
        ["Cafe Blue", "UPI", "₹450.00"],
        ["-", "credit card", "+₹200.00"],
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
    assert "spent ₹740.00" in line
    assert "UPI 2" in line and "credit card 1" in line
    assert "largest ₹600.00" in line
    assert "received ₹200.00" in line


def test_only_max_items_rows_are_shown_but_the_totals_cover_every_transaction():
    pairs = [(email(str(i)), Category.TRANSACTIONS) for i in range(5)]
    found = {str(i): tx(str(i), "10.00") for i in range(5)}
    table = run(pairs, TX_CONFIG, transactions=found).sections[0].table
    assert len(table.rows) == 3 and table.omitted == 2
    assert "5 transactions" in table.summary and "spent ₹50.00" in table.summary


def test_transaction_alerts_with_no_amount_are_listed_not_counted():
    pairs = [
        (email("1"), Category.TRANSACTIONS),
        (email("2", "odd alert"), Category.TRANSACTIONS),
    ]
    table = run(pairs, TX_CONFIG, transactions={"1": tx("1")}).sections[0].table
    assert len(table.rows) == 1 and [r.email_id for r in table.unlisted] == ["2"]
    assert "1 transaction" in table.summary


# ---- Round 1 clean-ups: rupee sign, relative due dates, repeated bills, readable payees ----


def due_cell(due, now=NOW):
    pairs = [(email("1"), Category.BILLS)]
    row = run(pairs, BILLS_CONFIG, bills={"1": bill(due=due)}, now=now)
    return row.sections[0].table.rows[0].cells[3]


def test_due_dates_read_as_today_tomorrow_or_in_n_days():
    # NOW is 8 Nov 2026 (8:30 AM IST)
    assert due_cell(date(2026, 11, 8)) == "today"
    assert due_cell(date(2026, 11, 9)) == "tomorrow"
    assert due_cell(date(2026, 11, 12)) == "in 4 days"


def test_a_far_off_due_date_is_a_short_date_and_a_past_one_is_overdue():
    assert due_cell(date(2026, 12, 20)) == "20 Dec"
    assert due_cell(date(2026, 11, 5)) == "overdue"


def test_without_a_clock_the_due_date_stays_a_plain_date():
    assert due_cell(date(2026, 11, 9), now=None) == "2026-11-09"


def test_other_currencies_keep_their_code():
    pairs = [(email("1"), Category.RECEIPTS)]
    found = {"1": bill("Shop", amount="20.00", currency="USD", due=None)}
    row = run(pairs, BILLS_CONFIG, bills=found).sections[0].table.rows[0]
    assert row.cells[2] == "USD 20.00"


def repeated_bills(n=4):
    pairs = [(email(str(i)), Category.BILLS) for i in range(n)]
    found = {str(i): bill("Furlenco", "496.19", date(2026, 11, 20)) for i in range(n)}
    return run(pairs, BILLS_CONFIG, bills=found).sections[0]


def test_identical_bills_collapse_to_one_row_marked_with_how_many():
    table = repeated_bills().table
    assert len(table.rows) == 1
    assert table.rows[0].cells[1] == "Furlenco ×4"
    assert table.rows[0].email_id == "0"  # links to the newest of them


def test_identical_bills_are_counted_once_in_the_total_but_the_section_still_counts_the_mail():
    section = repeated_bills()
    assert "1 bill: ₹496.19" in section.table.summary
    assert section.count == 4


def test_bills_that_differ_in_amount_or_due_date_stay_separate():
    pairs = [(email(str(i)), Category.BILLS) for i in range(3)]
    found = {
        "0": bill("Furlenco", "496.19", date(2026, 11, 20)),
        "1": bill("Furlenco", "496.19", date(2026, 12, 20)),
        "2": bill("Furlenco", "500.00", date(2026, 11, 20)),
    }
    rows = run(pairs, BILLS_CONFIG, bills=found).sections[0].table.rows
    assert len(rows) == 3


def payee_cell(payee, via="UPI"):
    pairs = [(email("1"), Category.TRANSACTIONS)]
    found = {"1": tx("1", payee=payee, via=via)}
    return run(pairs, TX_CONFIG, transactions=found).sections[0].table.rows[0].cells[0]


def test_a_masked_upi_handle_loses_its_asterisks_and_bank_suffix():
    assert payee_cell("*******payu@hdfcbank") == "payu"


def test_an_unreadable_upi_handle_becomes_upi_payment():
    assert payee_cell("*******1234@okaxis") == "UPI payment"
    assert payee_cell("****") == "UPI payment"


def test_a_normal_payee_name_is_left_alone():
    assert payee_cell("Cafe Blue") == "Cafe Blue"
    assert payee_cell(None, via="credit card") == "-"


# ---- Round 3c: one Money table for bills, receipts and payments, with statements beside it ----

MONEY_CONFIG = DigestConfig(
    sections=[
        DigestSection(
            title="Money",
            categories=["bills", "receipts", "transactions", "statements"],
            mode="table",
            table="money",
            max_items=30,
        )
    ]
)


def money_section(pairs, bills=None, transactions=None, now=NOW, config=MONEY_CONFIG):
    return run(pairs, config, bills=bills, transactions=transactions, now=now).sections[
        0
    ]


def test_bills_receipts_and_payments_share_one_table_with_bills_first():
    pairs = [
        (email("p1"), Category.TRANSACTIONS),
        (email("r1"), Category.RECEIPTS),
        (email("b1"), Category.BILLS),
        (email("p2"), Category.TRANSACTIONS),
    ]
    section = money_section(
        pairs,
        bills={
            "b1": bill("HDFC Bank", "5633.00", date(2026, 11, 9)),
            "r1": bill("Amazon.in", "85004.00", None),
        },
        transactions={
            "p1": tx("p1", "450.00", "Cafe Blue", "UPI", "debit"),
            "p2": tx("p2", "200.00", None, "credit card", "credit"),
        },
    )
    table = section.table
    assert table.columns == ["What", "Who", "Amount", "When"] and table.link_column == 1
    assert [r.cells for r in table.rows] == [
        ["bill", "HDFC Bank", "₹5,633.00", "tomorrow"],
        ["receipt", "Amazon.in", "₹85,004.00", "-"],
        ["spent", "Cafe Blue", "₹450.00", "UPI"],
        ["received", "-", "+₹200.00", "credit card"],
    ]
    assert section.count == 4


def test_the_money_summary_covers_bills_receipts_spending_and_money_in():
    pairs = [
        (email("b1"), Category.BILLS),
        (email("r1"), Category.RECEIPTS),
        (email("p1"), Category.TRANSACTIONS),
        (email("p2"), Category.TRANSACTIONS),
    ]
    line = money_section(
        pairs,
        bills={"b1": bill(amount="1000.00"), "r1": bill("Shop", amount="20.00")},
        transactions={
            "p1": tx("p1", "100.00", via="UPI"),
            "p2": tx("p2", "200.00", direction="credit"),
        },
    ).table.summary
    assert "1 bill: ₹1,000.00" in line and "1 receipt: ₹20.00" in line
    assert "spent ₹100.00" in line and "received ₹200.00" in line


def test_statements_are_a_separate_list_not_table_rows_and_not_no_amount_mail():
    pairs = [
        (email("s1", "Account statement"), Category.STATEMENTS),
        (email("b1"), Category.BILLS),
    ]
    table = money_section(pairs, bills={"b1": bill()}).table
    assert [r.email_id for r in table.statements] == ["s1"]
    assert [r.email_id for r in table.rows] == ["b1"]
    assert table.unlisted == []


def test_a_section_with_only_statements_still_works():
    section = money_section([(email("s1", "Account statement"), Category.STATEMENTS)])
    assert section.table.rows == [] and len(section.table.statements) == 1
    assert section.table.summary  # says something sensible


def test_money_mail_with_nothing_extracted_is_listed_as_no_amount_found():
    pairs = [
        (email("b1", "Odd offer"), Category.BILLS),
        (email("p1", "odd alert"), Category.TRANSACTIONS),
    ]
    table = money_section(pairs).table
    assert sorted(r.email_id for r in table.unlisted) == ["b1", "p1"]


def test_money_rows_beyond_the_limit_are_counted_and_the_totals_cover_them_all():
    config = DigestConfig(
        sections=[
            DigestSection(
                title="Money",
                categories=["transactions"],
                mode="table",
                table="money",
                max_items=2,
            )
        ]
    )
    pairs = [(email(str(i)), Category.TRANSACTIONS) for i in range(5)]
    found = {str(i): tx(str(i), "10.00") for i in range(5)}
    table = money_section(pairs, transactions=found, config=config).table
    assert len(table.rows) == 2 and table.omitted == 3
    assert "spent ₹50.00" in table.summary


def test_repeated_identical_bills_still_collapse_in_the_money_table():
    pairs = [(email(str(i)), Category.BILLS) for i in range(3)]
    found = {str(i): bill("Furlenco", "496.19", date(2026, 11, 20)) for i in range(3)}
    table = money_section(pairs, bills=found).table
    assert len(table.rows) == 1 and table.rows[0].cells[1] == "Furlenco ×3"
    assert "1 bill: ₹496.19" in table.summary


def test_a_bill_due_soon_in_the_money_table_is_highlighted():
    pairs = [(email("b1"), Category.BILLS), (email("p1"), Category.TRANSACTIONS)]
    table = money_section(
        pairs, bills={"b1": bill(due=date(2026, 11, 9))}, transactions={"p1": tx("p1")}
    ).table
    assert [r.highlight for r in table.rows] == [True, False]
