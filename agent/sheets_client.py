"""Log bills and receipts to the Google Sheet.

The Google `service` object is injected so tests use a fake. Ranges carry no tab name, so they
always mean the sheet's first tab. Values are written with RAW so text from an email (a vendor
name like `=IMPORTXML(...)`) is stored as plain text and never run as a formula.
"""

from agent.schemas import Bill, Category, Email

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


class SheetsClient:
    def __init__(self, service, spreadsheet_id: str) -> None:
        self._values = service.spreadsheets().values()
        self._id = spreadsheet_id

    def ensure_header(self) -> None:
        """Write the header row if the sheet is still empty."""
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

    def logged_email_ids(self) -> set[str]:
        """Ids of emails already in the sheet, read back from the Email link column."""
        rows = (
            self._values.get(
                spreadsheetId=self._id, range=f"{LINK_COLUMN}2:{LINK_COLUMN}"
            )
            .execute()
            .get("values", [])
        )
        return {
            row[0].rsplit("/", 1)[-1]
            for row in rows
            if row and row[0].startswith(LINK_PREFIX)
        }

    def log_bills(self, items: list[tuple[Email, Category, Bill]]) -> list[str]:
        """Append rows for emails not yet logged, in one call. Returns the ids appended."""
        self.ensure_header()
        already = self.logged_email_ids()
        new = [item for item in items if item[0].id not in already]
        if not new:
            return []
        self._values.append(
            spreadsheetId=self._id,
            range="A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [build_row(*item) for item in new]},
        ).execute()
        return [email.id for email, _, _ in new]
