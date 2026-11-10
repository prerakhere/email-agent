"""Matching payments to the bills and receipts they settle, inside the Money table.

Conservative on purpose: a wrong merge is worse than two rows, so anything ambiguous (several
possible partners on either side) or unknown (no arrival time) is left unmerged.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from langchain_core.runnables import RunnableLambda

from agent.digest import build_digest
from agent.digest_config import DigestConfig, DigestSection
from agent.digest_email import render_digest
from agent.nodes.transactions import Transaction
from agent.schemas import Bill, Category, Classification, Email

NOW = datetime(2026, 11, 9, 3, 0, tzinfo=UTC)  # 8:30 AM IST on 9 Nov
CONFIG = DigestConfig(
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


def exploding(_request):
    raise AssertionError("the money table must not call the model")


def mail(mid, at, sender="Shop <s@x.com>", subject="s"):
    return Email(
        id=mid,
        thread_id=f"t-{mid}",
        sender=sender,
        subject=subject,
        body_preview="b",
        received_at=at,
    )


def bill(vendor="Example Bank card", amount="8120.00", due=date(2026, 11, 10)):
    return Bill(
        vendor=vendor,
        amount=Decimal(amount),
        currency="INR",
        due_date=due,
        confidence=0.9,
    )


def pay(mid, amount="8120.00", payee="Example Bank", direction="debit", via="UPI"):
    return Transaction(
        email_id=mid,
        amount=Decimal(amount),
        currency="INR",
        payee=payee,
        via=via,
        direction=direction,
    )


def money(pairs, bills=None, transactions=None):
    emails = [e for e, _ in pairs]
    classes = {
        e.id: Classification(category=c, confidence=1.0, reason="r", source="llm")
        for e, c in pairs
    }
    return build_digest(
        emails,
        classes,
        CONFIG,
        RunnableLambda(exploding),
        RunnableLambda(exploding),
        bills=bills or {},
        transactions=transactions or {},
        now=NOW,
    )


def at(day, hour):
    return datetime(2026, 11, day, hour, 0, tzinfo=UTC)


def cells(content):
    return [r.cells for r in content.sections[0].table.rows]


# ---- a bill that has been paid ----


def test_a_payment_of_the_same_amount_after_the_bill_marks_it_paid_and_is_absorbed():
    pairs = [
        (mail("b1", at(9, 1)), Category.BILLS),
        (mail("p1", at(9, 6)), Category.TRANSACTIONS),
    ]
    content = money(pairs, {"b1": bill()}, {"p1": pay("p1")})
    assert cells(content) == [["bill", "Example Bank card", "₹8,120.00", "paid"]]
    section = content.sections[0]
    assert section.count == 2  # both mails are still counted
    assert not section.table.rows[0].highlight
    assert "likely paid" in section.table.summary
    assert "spent" not in section.table.summary


def test_a_paid_bill_is_not_counted_as_due_soon_in_the_headline_or_tiles():
    pairs = [
        (mail("b1", at(9, 1)), Category.BILLS),
        (mail("p1", at(9, 6)), Category.TRANSACTIONS),
    ]
    since, until = at(9, 2), at(10, 2)
    paid = render_digest(money(pairs, {"b1": bill()}, {"p1": pay("p1")}), since, until)
    unpaid = render_digest(money(pairs[:1], {"b1": bill()}), since, until)
    assert "due soon" not in paid.html and "due soon" not in paid.text
    assert "1 due soon" in unpaid.html and "1 due soon" in unpaid.text


def test_a_payment_that_arrived_before_the_bill_is_not_a_match():
    pairs = [
        (mail("b1", at(9, 6)), Category.BILLS),
        (mail("p1", at(9, 1)), Category.TRANSACTIONS),
    ]
    content = money(pairs, {"b1": bill()}, {"p1": pay("p1")})
    assert [c[0] for c in cells(content)] == ["bill", "spent"]


def test_a_different_amount_is_not_a_match():
    pairs = [
        (mail("b1", at(9, 1)), Category.BILLS),
        (mail("p1", at(9, 6)), Category.TRANSACTIONS),
    ]
    content = money(pairs, {"b1": bill()}, {"p1": pay("p1", "8000.00")})
    assert [c[0] for c in cells(content)] == ["bill", "spent"]


def test_two_payments_of_the_same_amount_are_ambiguous_so_nothing_is_merged():
    pairs = [
        (mail("b1", at(9, 1)), Category.BILLS),
        (mail("p1", at(9, 5)), Category.TRANSACTIONS),
        (mail("p2", at(9, 6)), Category.TRANSACTIONS),
    ]
    found = {"p1": pay("p1"), "p2": pay("p2")}
    content = money(pairs, {"b1": bill()}, found)
    assert [c[0] for c in cells(content)] == ["bill", "spent", "spent"]
    assert cells(content)[0][3] != "paid"


def test_two_bills_of_the_same_amount_are_ambiguous_so_nothing_is_merged():
    pairs = [
        (mail("b1", at(9, 1)), Category.BILLS),
        (mail("b2", at(9, 2)), Category.BILLS),
        (mail("p1", at(9, 6)), Category.TRANSACTIONS),
    ]
    bills = {"b1": bill("Power Co"), "b2": bill("Water Co")}
    content = money(pairs, bills, {"p1": pay("p1")})
    assert [c[0] for c in cells(content)] == ["bill", "bill", "spent"]


def test_money_received_is_never_matched_to_a_bill():
    pairs = [
        (mail("b1", at(9, 1)), Category.BILLS),
        (mail("p1", at(9, 6)), Category.TRANSACTIONS),
    ]
    content = money(pairs, {"b1": bill()}, {"p1": pay("p1", direction="credit")})
    assert [c[0] for c in cells(content)] == ["bill", "received"]


def test_without_arrival_times_nothing_is_merged():
    pairs = [
        (mail("b1", None), Category.BILLS),
        (mail("p1", None), Category.TRANSACTIONS),
    ]
    content = money(pairs, {"b1": bill()}, {"p1": pay("p1")})
    assert [c[0] for c in cells(content)] == ["bill", "spent"]


# ---- a receipt with an amount, and the payment alert for it ----


def test_a_receipt_and_a_same_day_same_amount_payment_become_one_row():
    pairs = [
        (mail("r1", at(9, 4)), Category.RECEIPTS),
        (mail("p1", at(9, 6)), Category.TRANSACTIONS),
    ]
    content = money(
        pairs, {"r1": bill("Amazon.in", "499.00", None)}, {"p1": pay("p1", "499.00")}
    )
    assert cells(content) == [["receipt", "Amazon.in", "₹499.00", "UPI"]]


def test_a_receipt_and_a_payment_on_different_days_stay_separate():
    pairs = [
        (mail("r1", at(8, 4)), Category.RECEIPTS),
        (mail("p1", at(9, 6)), Category.TRANSACTIONS),
    ]
    content = money(
        pairs, {"r1": bill("Amazon.in", "499.00", None)}, {"p1": pay("p1", "499.00")}
    )
    assert [c[0] for c in cells(content)] == ["receipt", "spent"]


# ---- a booking mail with no amount, and the bank alert that carries the amount ----


def booking_pairs(payee="Amazon Pay"):
    return [
        (
            mail(
                "r1",
                at(9, 4),
                sender="Amazon Pay <noreply@amazonpay.example>",
                subject="Your bus ticket is booked",
            ),
            Category.RECEIPTS,
        ),
        (
            mail("p1", at(9, 6), sender="Example Bank <a@bank.example>"),
            Category.TRANSACTIONS,
        ),
    ], {"p1": pay("p1", "450.00", payee)}


def test_a_booking_mail_with_no_amount_merges_with_the_one_payment_naming_the_same_brand():
    pairs, found = booking_pairs()
    content = money(pairs, transactions=found)
    assert cells(content) == [["receipt", "Amazon Pay", "₹450.00", "UPI"]]
    table = content.sections[0].table
    assert table.rows[0].email_id == "r1"  # the row links to the booking mail
    assert table.unlisted == []
    assert "spent" not in table.summary and "1 receipt: ₹450.00" in table.summary


def test_a_payment_to_an_unrelated_brand_is_not_merged_with_the_booking_mail():
    pairs, found = booking_pairs(payee="Cafe Blue")
    content = money(pairs, transactions=found)
    assert [c[0] for c in cells(content)] == ["spent"]
    assert [r.email_id for r in content.sections[0].table.unlisted] == ["r1"]


def test_two_same_day_payments_to_the_brand_are_ambiguous_so_nothing_is_merged():
    pairs, found = booking_pairs()
    pairs.append((mail("p2", at(9, 7)), Category.TRANSACTIONS))
    found["p2"] = pay("p2", "90.00", "Amazon Pay")
    content = money(pairs, transactions=found)
    assert [c[0] for c in cells(content)] == ["spent", "spent"]
    assert [r.email_id for r in content.sections[0].table.unlisted] == ["r1"]


def test_a_booking_mail_and_a_payment_on_different_days_are_not_merged():
    pairs, found = booking_pairs()
    pairs[1] = (mail("p1", at(8, 6)), Category.TRANSACTIONS)
    content = money(pairs, transactions=found)
    assert [c[0] for c in cells(content)] == ["spent"]
