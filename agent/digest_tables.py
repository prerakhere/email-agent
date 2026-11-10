"""Table sections of the digest: bills and transactions as compact rows, not one summary per mail.

Pure formatting over amounts that were already extracted from the mail, so no model call happens
here. Each table has a header, the shown rows, a one-line total (which covers EVERY row, even those
cut by max_items), and a list of the section's mails that had no extractable amount, so a promotional
mail that looked like a bill can never sit among the real bills.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from email.utils import parseaddr
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from agent.nodes.transactions import Transaction
from agent.profile import DEFAULT_SYMBOLS, Profile
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
    link_column: int = 0  # which column's text links to the Gmail message
    rows: list[TableRow]  # the rows shown (at most max_items)
    omitted: int = 0  # rows not shown
    summary: str  # one line; covers all rows, shown or not
    unlisted: list[EmailRef] = Field(
        default_factory=list
    )  # section mail with no amount found
    statements: list[EmailRef] = Field(
        default_factory=list
    )  # periodic records, no amount
    statements_omitted: int = 0  # statements not shown


@dataclass(frozen=True)
class Locale:
    """What depends on the reader: their time zone and the symbols of their currencies."""

    tz: ZoneInfo
    symbols: dict[str, str]

    @classmethod
    def from_profile(cls, profile: Profile | None) -> "Locale":
        profile = profile or Profile()
        return cls(ZoneInfo(profile.timezone), dict(profile.currency_symbols))


def money(
    amount: Decimal,
    currency: str,
    sign: str = "",
    symbols: dict[str, str] | None = None,
) -> str:
    """'₹1,500.00' for a currency with a symbol, 'CHF 20.00' (its code) for one without."""
    symbol = (DEFAULT_SYMBOLS if symbols is None else symbols).get(currency)
    if symbol:
        return f"{sign}{symbol}{amount:,.2f}"
    return f"{sign}{currency} {amount:,.2f}"


def due_label(due: date, today: date | None) -> str:
    """'today', 'tomorrow', 'in 4 days', a short date when far off, 'overdue' when past."""
    if today is None:
        return due.isoformat()
    days = (due - today).days
    if days < 0:
        return "overdue"
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    if days <= 14:
        return f"in {days} days"
    return f"{due.day} {due:%b}"


def clean_payee(payee: str | None, via: str) -> str:
    """Masked UPI handles ('*****name@bank') become 'name'; unreadable ones 'UPI payment'."""
    if not payee:
        return "-"
    if "*" not in payee and "@" not in payee:
        return payee
    name = payee.lstrip("*").strip().split("@")[0]
    if len(re.findall(r"[A-Za-z]", name)) >= 3:
        return name
    return "UPI payment" if via == "UPI" else "-"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _total(items: list[tuple[Decimal, str]], symbols: dict[str, str]) -> str:
    """Sum per currency, e.g. '₹1,500.50' or '₹10.00 + $20.00'."""
    sums: dict[str, Decimal] = defaultdict(Decimal)
    for amount, currency in items:
        sums[currency] += amount
    return " + ".join(
        money(total, currency, symbols=symbols)
        for currency, total in sorted(sums.items())
    )


def _refs(emails: list[Email]) -> list[EmailRef]:
    return [EmailRef(email_id=e.id, sender=e.sender, subject=e.subject) for e in emails]


BillKey = tuple[
    str, str, Decimal, str, date | None
]  # kind, vendor, amount, currency, due


def _bill_groups(
    ordered: list[Email],
    classifications: dict[str, Classification],
    bills: dict[str, Bill],
    bills_first: bool = False,
) -> dict[BillKey, list[tuple[Email, Bill]]]:
    """Bills and receipts with an extracted amount, soonest due date first (undated last), and the
    same biller, amount and due date seen several times (reminders) merged into ONE bill, which
    is shown as one row marked with how many and counted once in the total."""
    found = [(e, bills[e.id]) for e in ordered if e.id in bills]

    def kind_of(email: Email) -> str:
        is_bill = classifications[email.id].category == Category.BILLS
        return "bill" if is_bill else "receipt"

    # The sort is stable, so ties keep newest-first order.
    found.sort(
        key=lambda pair: (
            bills_first and kind_of(pair[0]) != "bill",
            pair[1].due_date is None,
            pair[1].due_date or date.max,
        )
    )
    groups: dict[BillKey, list[tuple[Email, Bill]]] = {}
    for email, bill in found:
        key = (kind_of(email), bill.vendor, bill.amount, bill.currency, bill.due_date)
        groups.setdefault(key, []).append((email, bill))
    return groups


def _bill_row(
    key: BillKey,
    members: list[tuple[Email, Bill]],
    today: date | None,
    soon: date | None,
    symbols: dict[str, str],
) -> TableRow:
    kind, vendor, amount, currency, due = key
    times = f" ×{len(members)}" if len(members) > 1 else ""
    return TableRow(
        email_id=members[0][0].id,
        cells=[
            kind,
            f"{vendor}{times}",
            money(amount, currency, symbols=symbols),
            due_label(due, today) if due else "-",
        ],
        highlight=bool(soon and due and due <= soon),
    )


def _bill_summary_parts(
    groups: dict[BillKey, list[tuple[Email, Bill]]], symbols: dict[str, str]
) -> list[str]:
    parts = []
    for word in ("bill", "receipt"):
        group = [(k[2], k[3]) for k in groups if k[0] == word]
        if group:
            parts.append(f"{_plural(len(group), word)}: {_total(group, symbols)}")
    return parts


def bills_table(
    ordered: list[Email],
    classifications: dict[str, Classification],
    bills: dict[str, Bill],
    max_items: int,
    now: datetime | None,
    locale: Locale | None = None,
) -> TableData:
    locale = locale or Locale.from_profile(None)
    today = now.astimezone(locale.tz).date() if now else None
    soon = today + timedelta(days=DUE_SOON_DAYS) if today else None
    groups = _bill_groups(ordered, classifications, bills)
    rows = [
        _bill_row(key, members, today, soon, locale.symbols)
        for key, members in groups.items()
    ]
    return TableData(
        columns=["Type", "Biller", "Amount", "Due"],
        link_column=1,
        rows=rows[:max_items],
        omitted=max(len(rows) - max_items, 0),
        summary=" · ".join(_bill_summary_parts(groups, locale.symbols))
        or "No amounts found",
        unlisted=_refs([e for e in ordered if e.id not in bills]),
    )


def _spending_parts(found: list[Transaction], symbols: dict[str, str]) -> list[str]:
    spent = [tx for tx in found if tx.direction == "debit"]
    received = [tx for tx in found if tx.direction == "credit"]
    parts = []
    if spent:
        by_via = Counter(tx.via for tx in spent).most_common()
        how = ", ".join(
            f"{via} {n}" for via, n in sorted(by_via, key=lambda p: (-p[1], p[0]))
        )
        parts.append(
            f"spent {_total([(tx.amount, tx.currency) for tx in spent], symbols)} ({how})"
        )
    if received:
        parts.append(
            f"received {_total([(tx.amount, tx.currency) for tx in received], symbols)}"
        )
    return parts


# Words too common to tie a booking mail to a payment ("Your ticket", "Payment confirmed", ...).
_GENERIC_WORDS = {
    "your", "from", "this", "that", "with", "order", "orders", "booking", "ticket",
    "tickets", "payment", "confirmed", "confirmation", "receipt", "india", "limited",
    "private", "services", "email", "noreply", "reply", "bank", "card", "upi",
}  # fmt: skip


def _local_day(email: Email, tz: ZoneInfo) -> date | None:
    if email.received_at is None:
        return None
    return email.received_at.astimezone(tz).date()


def _brand_words(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if len(w) >= 4 and w not in _GENERIC_WORDS}


def _match_payments(
    ordered: list[Email],
    classifications: dict[str, Classification],
    groups: dict[BillKey, list[tuple[Email, Bill]]],
    bills: dict[str, Bill],
    debits: list[Transaction],
    tz: ZoneInfo,
) -> list[tuple[str, object, str]]:
    """Which payment settles which bill or receipt, as (rule, what, payment email id).

    Conservative: a pair counts only when neither side has another possible partner, because a
    wrong merge is worse than two rows. Unknown arrival times never match.
    """
    by_id = {e.id: e for e in ordered}
    pairs: list[tuple[str, object, str]] = []
    for key, members in groups.items():
        kind, vendor, amount, currency, _due = key
        arrivals = [e.received_at for e, _ in members]
        if any(a is None for a in arrivals):
            continue
        for tx in debits:
            if (tx.amount, tx.currency) != (amount, currency):
                continue
            tx_email = by_id[tx.email_id]
            if kind == "bill":
                # Paid after the bill arrived (the same day or later), AND the payment names the
                # biller: the amount alone is not evidence (a ₹499 bill and an unrelated ₹499
                # purchase would otherwise hide a bill that is still due).
                names_biller = _brand_words(vendor) & _brand_words(tx.payee or "")
                after = tx_email.received_at and tx_email.received_at >= min(arrivals)
                if names_biller and after:
                    pairs.append(("bill", key, tx.email_id))
            elif _local_day(tx_email, tz) and _local_day(tx_email, tz) == _local_day(
                members[0][0], tz
            ):
                pairs.append(("receipt", key, tx.email_id))
    for email in ordered:
        is_receipt = classifications[email.id].category == Category.RECEIPTS
        day = _local_day(email, tz)
        if not is_receipt or email.id in bills or day is None:
            continue
        name = parseaddr(email.sender)[0] or email.sender
        words = _brand_words(f"{name} {email.subject}")
        for tx in debits:
            tx_email = by_id[tx.email_id]
            if _local_day(tx_email, tz) == day and words & _brand_words(tx.payee or ""):
                pairs.append(("booking", email.id, tx.email_id))
    lefts = Counter((rule, what) for rule, what, _ in pairs)
    rights = Counter(tx_id for _, _, tx_id in pairs)
    return [p for p in pairs if lefts[(p[0], p[1])] == 1 and rights[p[2]] == 1]


def money_table(
    ordered: list[Email],
    classifications: dict[str, Classification],
    bills: dict[str, Bill],
    transactions: dict[str, Transaction],
    max_items: int,
    now: datetime | None,
    locale: Locale | None = None,
) -> TableData:
    """Bills, receipts and payments in ONE table (bills first), statements as a separate list.

    A payment that settles a bill marks it paid; a payment that matches a receipt (or a booking
    mail that carries no amount) is folded into it, so one purchase is one row."""
    locale = locale or Locale.from_profile(None)
    symbols = locale.symbols
    today = now.astimezone(locale.tz).date() if now else None
    soon = today + timedelta(days=DUE_SOON_DAYS) if today else None
    groups = _bill_groups(ordered, classifications, bills, bills_first=True)
    found = [transactions[e.id] for e in ordered if e.id in transactions]
    by_tx = {tx.email_id: tx for tx in found}
    debits = [tx for tx in found if tx.direction == "debit"]
    matches = _match_payments(
        ordered, classifications, groups, bills, debits, locale.tz
    )
    paid = {what for rule, what, _ in matches if rule == "bill"}
    via_for = {
        what: by_tx[tx_id].via for rule, what, tx_id in matches if rule == "receipt"
    }
    bookings = {
        what: by_tx[tx_id] for rule, what, tx_id in matches if rule == "booking"
    }
    absorbed = {tx_id for _, _, tx_id in matches}

    rows = []
    for key, members in groups.items():
        row = _bill_row(key, members, today, soon, symbols)
        if key in paid:
            row.cells[3], row.highlight = "paid", False
        elif key in via_for:
            row.cells[3] = via_for[key]
        rows.append(row)
    for email_id, tx in bookings.items():
        rows.append(
            TableRow(
                email_id=email_id,
                cells=[
                    "receipt",
                    clean_payee(tx.payee, tx.via),
                    money(tx.amount, tx.currency, symbols=symbols),
                    tx.via,
                ],
            )
        )
    left_over = [tx for tx in found if tx.email_id not in absorbed]
    for tx in left_over:
        credit = tx.direction == "credit"
        rows.append(
            TableRow(
                email_id=tx.email_id,
                cells=[
                    "received" if credit else "spent",
                    clean_payee(tx.payee, tx.via),
                    money(tx.amount, tx.currency, "+" if credit else "", symbols),
                    tx.via,
                ],
            )
        )

    statements = [
        e for e in ordered if classifications[e.id].category == Category.STATEMENTS
    ]
    due = [(k[2], k[3]) for k in groups if k[0] == "bill" and k not in paid]
    receipts = [(k[2], k[3]) for k in groups if k[0] == "receipt"]
    receipts += [(tx.amount, tx.currency) for tx in bookings.values()]
    parts = []
    if due:
        parts.append(f"{_plural(len(due), 'bill')}: {_total(due, symbols)}")
    if paid:
        parts.append(f"{len(paid)} likely paid")
    if receipts:
        parts.append(
            f"{_plural(len(receipts), 'receipt')}: {_total(receipts, symbols)}"
        )
    parts += _spending_parts(left_over, symbols)
    if not parts and statements:
        parts = [_plural(len(statements), "statement")]
    return TableData(
        columns=["What", "Who", "Amount", "When"],
        link_column=1,
        rows=rows[:max_items],
        omitted=max(len(rows) - max_items, 0),
        summary=" · ".join(parts) or "No amounts found",
        statements=_refs(statements[:max_items]),
        statements_omitted=max(len(statements) - max_items, 0),
        unlisted=_refs(
            [
                e
                for e in ordered
                if e.id not in bills
                and e.id not in transactions
                and e.id not in bookings
                and classifications[e.id].category != Category.STATEMENTS
            ]
        ),
    )


def transactions_table(
    ordered: list[Email],
    transactions: dict[str, Transaction],
    max_items: int,
    locale: Locale | None = None,
) -> TableData:
    symbols = (locale or Locale.from_profile(None)).symbols
    found = [transactions[e.id] for e in ordered if e.id in transactions]
    rows = [
        TableRow(
            email_id=tx.email_id,
            cells=[
                clean_payee(tx.payee, tx.via),
                tx.via,
                money(
                    tx.amount,
                    tx.currency,
                    "+" if tx.direction == "credit" else "",
                    symbols,
                ),
            ],
        )
        for tx in found
    ]

    summary = "No amounts found"
    if found:
        parts = [_plural(len(found), "transaction")] + _spending_parts(found, symbols)
        spent = [tx for tx in found if tx.direction == "debit"]
        if spent:
            largest = max(spent, key=lambda tx: tx.amount)
            # right after the "spent" part, before any "received" part
            parts.insert(
                2, f"largest {money(largest.amount, largest.currency, symbols=symbols)}"
            )
        summary = " · ".join(parts)
    return TableData(
        columns=["To", "Via", "Amount"],
        link_column=0,
        rows=rows[:max_items],
        omitted=max(len(rows) - max_items, 0),
        summary=summary,
        unlisted=_refs([e for e in ordered if e.id not in transactions]),
    )
