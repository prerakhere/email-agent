"""Log bills and receipts to the Google Sheet.

The Google `service` object is injected so tests use a fake. Ranges carry no tab name, so they
always mean the sheet's first tab. Values are written with RAW so text from an email (a vendor
name like `=IMPORTXML(...)`) is stored as plain text and never run as a formula.
"""

from agent.schemas import Bill, Category, Email


class SheetLayoutError(RuntimeError):
    """The sheet's first row is not the header this agent writes under."""


HEADER = [
    "Date received",
    "Type",
    "Biller",
    "Amount",
    "Currency",
    "Due date",
    "Status",
    "Email link",
]
LINK_COLUMN = "H"
LOW_CONFIDENCE = 0.7
LINK_PREFIX = "https://mail.google.com/mail/u/0/#all/"


def email_link(email_id: str) -> str:
    return f"{LINK_PREFIX}{email_id}"


def build_row(email: Email, category: Category, bill: Bill) -> list:
    """One sheet row in HEADER order. Only bills and receipts are logged."""
    if category not in (Category.BILLS, Category.RECEIPTS):
        raise ValueError(f"Only bills or receipts can be logged, got {category.value}")
    is_bill = category == Category.BILLS
    if bill.confidence < LOW_CONFIDENCE:
        status = "check"  # shaky extraction: make the row stand out for a human look
    else:
        status = "unpaid" if is_bill else "paid"
    return [
        email.received_at.date().isoformat() if email.received_at else "",
        "bill" if is_bill else "receipt",
        bill.vendor,
        float(bill.amount),
        bill.currency,
        bill.due_date.isoformat() if bill.due_date else "",
        status,
        email_link(email.id),
    ]


def _number(value) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _email_ids(rows: list[list]) -> set[str]:
    """Email ids found in the Email link column of already-logged rows."""
    return {
        row[7].rsplit("/", 1)[-1]
        for row in rows
        if len(row) > 7 and str(row[7]).startswith(LINK_PREFIX)
    }


def _bill_key(row: list) -> tuple | None:
    """Identity of a bill across reminder emails: biller, amount, currency and due date.

    Only bills WITH a due date have one: without it, the same subscription amount in two
    different months would wrongly count as one bill. Receipts are matched by email instead.
    """
    if len(row) < 6 or str(row[1]) != "bill" or not str(row[5]).strip():
        return None
    amount = _number(row[3])
    if amount is None:
        return None
    return (
        str(row[2]).strip().lower(),
        amount,
        str(row[4]).strip().upper(),
        str(row[5]).strip(),
    )


class SheetsClient:
    def __init__(self, service, spreadsheet_id: str) -> None:
        self._values = service.spreadsheets().values()
        self._id = spreadsheet_id

    def ensure_header(self) -> None:
        """Write the header if the sheet is empty; refuse to write under any other header."""
        existing = (
            self._values.get(spreadsheetId=self._id, range=f"A1:{LINK_COLUMN}1")
            .execute()
            .get("values")
        )
        if not existing:
            self._values.update(
                spreadsheetId=self._id,
                range=f"A1:{LINK_COLUMN}1",
                valueInputOption="RAW",
                body={"values": [HEADER]},
            ).execute()
        elif [str(c).strip() for c in existing[0]] != HEADER:
            raise SheetLayoutError(
                "The sheet's first row does not match the agent's columns, so nothing was "
                f"written. Found: {existing[0]}. Expected: {HEADER}."
            )

    def _logged_rows(self) -> list[list]:
        return (
            self._values.get(spreadsheetId=self._id, range=f"A2:{LINK_COLUMN}")
            .execute()
            .get("values", [])
        )

    def logged_email_ids(self) -> set[str]:
        """Ids of emails already in the sheet, read back from the Email link column."""
        return _email_ids(self._logged_rows())

    def log_bills(self, items: list[tuple[Email, Category, Bill]]) -> list[str]:
        """Append rows for what is not yet logged, in one call. Returns the email ids appended.

        Skipped: an email already in the sheet, and a bill whose biller/amount/currency/due
        date already appear (a reminder mail), whether in the sheet or earlier in this run.
        """
        self.ensure_header()
        rows = self._logged_rows()
        seen_ids = _email_ids(rows)
        seen_bills = {key for row in rows if (key := _bill_key(row)) is not None}
        new_rows, appended = [], []
        for email, category, bill in items:
            row = build_row(email, category, bill)
            key = _bill_key(row)
            if email.id in seen_ids or (key is not None and key in seen_bills):
                continue
            seen_ids.add(email.id)
            if key is not None:
                seen_bills.add(key)
            new_rows.append(row)
            appended.append(email.id)
        if not new_rows:
            return []
        self._values.append(
            spreadsheetId=self._id,
            range="A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": new_rows},
        ).execute()
        return appended
