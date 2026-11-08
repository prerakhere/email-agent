"""Table sections of the digest: bills and transactions as compact rows, not one summary per mail.

Pure formatting over amounts that were already extracted from the mail, so no model call happens
here. Each table has a header, the shown rows, a one-line total (which covers EVERY row, even those
cut by max_items), and a list of the section's mails that had no extractable amount, so a promotional
mail that looked like a bill can never sit among the real bills.
"""

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel, Field

from agent.nodes.transactions import Transaction
from agent.schemas import Bill, Category, Classification, Email

DUE_SOON_DAYS = 3


class EmailRef(BaseModel):
    """Enough to show a clickable line for an email."""

    email_id: str
    sender: str
    subject: str


class TableRow(BaseModel):
    email_id: str
    cells: list[str]
    highlight: bool = False  # e.g. a bill due within a few days


class TableData(BaseModel):
    columns: list[str]
    rows: list[TableRow]  # the rows shown (at most max_items)
    omitted: int = 0  # rows not shown
    summary: str  # one line; covers all rows, shown or not
    unlisted: list[EmailRef] = Field(
        default_factory=list
    )  # section mail with no amount found


def money(amount: Decimal, currency: str, sign: str = "") -> str:
    return f"{sign}{currency} {amount:,.2f}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _total(items: list[tuple[Decimal, str]]) -> str:
    """Sum per currency, e.g. 'INR 1,500.50' or 'INR 10.00 + USD 20.00'."""
    sums: dict[str, Decimal] = defaultdict(Decimal)
    for amount, currency in items:
        sums[currency] += amount
    return " + ".join(
        money(total, currency) for currency, total in sorted(sums.items())
    )


def _refs(emails: list[Email]) -> list[EmailRef]:
    return [EmailRef(email_id=e.id, sender=e.sender, subject=e.subject) for e in emails]


def bills_table(
    ordered: list[Email],
    classifications: dict[str, Classification],
    bills: dict[str, Bill],
    max_items: int,
    now: datetime | None,
) -> TableData:
    found = [(e, bills[e.id]) for e in ordered if e.id in bills]
    # Soonest due date first, undated last; the sort is stable so ties keep newest-first order.
    found.sort(
        key=lambda pair: (pair[1].due_date is None, pair[1].due_date or date.max)
    )
    today = now.date() if now else None
    soon = today + timedelta(days=DUE_SOON_DAYS) if today else None

    rows = []
    for email, bill in found:
        kind = (
            "bill"
            if classifications[email.id].category == Category.BILLS
            else "receipt"
        )
        due = bill.due_date
        rows.append(
            TableRow(
                email_id=email.id,
                cells=[
                    kind,
                    bill.vendor,
                    money(bill.amount, bill.currency),
                    due.isoformat() if due else "-",
                ],
                highlight=bool(soon and due and due <= soon),
            )
        )

    parts = []
    for word, category_is_bill in (("bill", True), ("receipt", False)):
        group = [
            (bill.amount, bill.currency)
            for email, bill in found
            if (classifications[email.id].category == Category.BILLS)
            == category_is_bill
        ]
        if group:
            parts.append(f"{_plural(len(group), word)}: {_total(group)}")
    return TableData(
        columns=["Type", "Biller", "Amount", "Due"],
        rows=rows[:max_items],
        omitted=max(len(rows) - max_items, 0),
        summary=" · ".join(parts) or "No amounts found",
        unlisted=_refs([e for e in ordered if e.id not in bills]),
    )


def transactions_table(
    ordered: list[Email], transactions: dict[str, Transaction], max_items: int
) -> TableData:
    found = [transactions[e.id] for e in ordered if e.id in transactions]
    rows = [
        TableRow(
            email_id=tx.email_id,
            cells=[
                money(tx.amount, tx.currency, "+" if tx.direction == "credit" else ""),
                tx.via,
                tx.payee or "-",
            ],
        )
        for tx in found
    ]

    summary = "No amounts found"
    if found:
        spent = [tx for tx in found if tx.direction == "debit"]
        received = [tx for tx in found if tx.direction == "credit"]
        parts = [_plural(len(found), "transaction")]
        if spent:
            by_via = Counter(tx.via for tx in spent).most_common()
            how = ", ".join(
                f"{via} {n}" for via, n in sorted(by_via, key=lambda p: (-p[1], p[0]))
            )
            largest = max(spent, key=lambda tx: tx.amount)
            parts.append(
                f"spent {_total([(tx.amount, tx.currency) for tx in spent])} ({how})"
            )
            parts.append(f"largest {money(largest.amount, largest.currency)}")
        if received:
            parts.append(
                f"received {_total([(tx.amount, tx.currency) for tx in received])}"
            )
        summary = " · ".join(parts)
    return TableData(
        columns=["Amount", "Via", "To"],
        rows=rows[:max_items],
        omitted=max(len(rows) - max_items, 0),
        summary=summary,
        unlisted=_refs([e for e in ordered if e.id not in transactions]),
    )
