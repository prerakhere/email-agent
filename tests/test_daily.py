import logging
import re
from datetime import UTC, date, datetime
from decimal import Decimal

from langchain_core.runnables import RunnableLambda

from agent.daily import execute_daily, prepare_daily, run_daily
from agent.digest_config import DEFAULT_CONFIG
from agent.nodes.classify import LLMBatch, LLMItem
from agent.nodes.extract import LLMBill
from agent.nodes.summarize import GroupText, SummaryBatch, SummaryItem
from agent.nodes.transactions import LLMTransactionBatch, LLMTransactionItem
from agent.schemas import Category, Email

SINCE = datetime(2026, 11, 8, 0, 30, tzinfo=UTC)  # 6:00 AM IST
UNTIL = datetime(2026, 11, 9, 0, 30, tzinfo=UTC)
LABEL_IDS = {"Agent/Job-Alerts": "L_jobs"}


class FakeGmail:
    def __init__(self, emails):
        self._emails = emails
        self.added: list[tuple[str, str]] = []
        self.moved: list[tuple[str, str]] = []
        self.sent: list[tuple[str, str, str]] = []
        self.fail_labels = False
        self.fail_send = False

    def fetch_since(self, since, max_results=500):
        return self._emails

    def label_ids_by_name(self):
        return LABEL_IDS

    def list_label_names(self):
        return list(LABEL_IDS)

    def ensure_label(self, name):
        if self.fail_labels:
            raise RuntimeError("labels down: private text")
        return f"id:{name}"

    def add_label(self, email_id, label_id):
        self.added.append((email_id, label_id))

    def move_to_label(self, email_id, label_id):
        self.moved.append((email_id, label_id))

    def send_to_self(self, subject, text, html):
        if self.fail_send:
            raise RuntimeError("send down: private text")
        self.sent.append((subject, text, html))
        return "sent-1"


class FakeSheets:
    def __init__(self, fail=False):
        self.calls: list[list] = []
        self.fail = fail

    def log_bills(self, items):
        if self.fail:
            raise RuntimeError("sheet down: private text")
        self.calls.append(items)
        return [email.id for email, _, _ in items]


def subjects_in(request):
    return re.findall(r"^Subject: (.*)$", request["emails"], re.MULTILINE)


class Models:
    """Fake chains. `classified` records every subject the classifier is asked about."""

    def __init__(self):
        self.classified: list[str] = []
        self.summarized: list[str] = []
        self.tx_extractor = RunnableLambda(self._tx)
        self.classifier = RunnableLambda(self._classify)
        self.extractor = RunnableLambda(self._extract)
        self.summarizer = RunnableLambda(self._summarize)
        self.group = RunnableLambda(lambda _r: GroupText(summary="A roundup."))

    def _classify(self, request):
        items = []
        for n, subject in enumerate(subjects_in(request), start=1):
            self.classified.append(subject)
            if subject.startswith("UPI"):
                category = Category.TRANSACTIONS
            elif subject.startswith("Statement"):
                category = Category.BILLS
            elif subject.startswith("Interview"):
                category = Category.IMPORTANT
            else:
                category = Category.NEWSLETTERS
            items.append(
                LLMItem(index=n, category=category, confidence=0.95, reason="r")
            )
        return LLMBatch(items=items)

    def _extract(self, _request):
        return LLMBill(
            vendor="HDFC Bank",
            amount=5633.0,
            currency="INR",
            due_date=date(2026, 11, 9),
            confidence=0.9,
        )

    def _tx(self, request):
        n = len(subjects_in(request))
        return LLMTransactionBatch(
            items=[
                LLMTransactionItem(
                    index=i, amount=50.0, currency="INR", payee="Cafe", via="UPI"
                )
                for i in range(1, n + 1)
            ]
        )

    def _summarize(self, request):
        self.summarized.extend(subjects_in(request))
        return SummaryBatch(
            items=[
                SummaryItem(index=n, summary=f"About {s}.")
                for n, s in enumerate(subjects_in(request), start=1)
            ]
        )


def email(mid, subject, labels=("INBOX",)):
    return Email(
        id=mid,
        thread_id=f"t-{mid}",
        sender=f"S <{mid}@x.com>",
        subject=subject,
        body_preview="body",
        label_ids=list(labels),
    )


EMAILS = [
    email("1", "Interview next week"),
    email("2", "Statement for October"),
    email("3", "Weekly reading"),
    email("4", "5 new jobs", labels=("INBOX", "L_jobs")),  # already labelled
]


def go(gmail=None, sheets="default", apply=True, models=None, emails=None, **kwargs):
    gmail = gmail or FakeGmail(emails if emails is not None else EMAILS)
    sheets = FakeSheets() if sheets == "default" else sheets
    models = models or Models()
    result = run_daily(
        gmail,
        sheets,
        {},
        DEFAULT_CONFIG,
        models.classifier,
        models.extractor,
        models.summarizer,
        models.group,
        since=SINCE,
        until=UNTIL,
        apply=apply,
        **kwargs,
    )
    return result, gmail, sheets, models


def test_a_real_run_logs_bills_labels_unlabelled_mail_and_sends_the_digest():
    result, gmail, sheets, _ = go()
    assert result.rows_added == ["2"]
    assert len(sheets.calls) == 1
    assert sorted(email_id for email_id, _ in gmail.added) == [
        "1",
        "2",
        "3",
    ]  # not the labelled one
    assert len(gmail.sent) == 1 and result.digest_message_id == "sent-1"
    assert "4 emails" in gmail.sent[0][0]
    assert result.errors == []


def test_mail_is_classified_once_not_once_for_labels_and_again_for_the_digest():
    _, _, _, models = go()
    # the agent's own earlier label is re-checked in the digest window, so "5 new jobs" is asked too;
    # each mail is asked about exactly once
    assert sorted(models.classified) == [
        "5 new jobs",
        "Interview next week",
        "Statement for October",
        "Weekly reading",
    ]


def test_a_dry_run_changes_and_sends_nothing_but_still_builds_the_digest():
    result, gmail, sheets, _ = go(apply=False)
    assert gmail.added == [] and gmail.moved == [] and gmail.sent == []
    assert sheets.calls == []
    assert result.rendered.subject.startswith("Inbox digest")
    assert result.digest_message_id is None and result.rows_added == []
    assert result.planned_labels == 3 and result.planned_rows == 1


def test_a_sheet_failure_does_not_stop_the_labels_or_the_digest():
    result, gmail, _, _ = go(sheets=FakeSheets(fail=True))
    assert result.errors == ["log_bills: RuntimeError"]
    assert len(gmail.added) == 3 and len(gmail.sent) == 1


def test_a_labelling_failure_does_not_stop_the_digest():
    gmail = FakeGmail(EMAILS)
    gmail.fail_labels = True
    result, gmail, sheets, _ = go(gmail=gmail)
    assert result.errors == ["apply_labels: RuntimeError"]
    assert len(gmail.sent) == 1 and len(sheets.calls) == 1


def test_a_failed_send_is_reported_after_the_other_steps_finished():
    gmail = FakeGmail(EMAILS)
    gmail.fail_send = True
    result, gmail, sheets, _ = go(gmail=gmail)
    assert result.errors == ["send_digest: RuntimeError"]
    assert result.digest_message_id is None
    assert len(gmail.added) == 3 and len(sheets.calls) == 1


def test_errors_name_the_step_and_error_type_but_never_the_message():
    gmail = FakeGmail(EMAILS)
    gmail.fail_send = True
    result, *_ = go(gmail=gmail, sheets=FakeSheets(fail=True))
    assert result.errors == ["log_bills: RuntimeError", "send_digest: RuntimeError"]
    assert "private" not in " ".join(result.errors)


def test_labelling_only_adds_labels_unless_told_to_move_mail_out_of_the_inbox():
    _, gmail, _, _ = go()
    assert gmail.moved == [] and len(gmail.added) == 3
    _, gmail, _, _ = go(keep_in_inbox=False)
    assert gmail.added == []
    # important mail never leaves the inbox; the bill and the newsletter do
    assert sorted(email_id for email_id, _ in gmail.moved) == ["2", "3"]


def test_an_empty_window_still_sends_a_digest_that_says_so():
    _result, gmail, sheets, _ = go(emails=[])
    assert len(gmail.sent) == 1 and "No new mail" in gmail.sent[0][1]
    assert sheets.calls == [] and gmail.added == []


def test_without_a_sheets_client_bills_are_skipped_without_an_error():
    result, gmail, _, _ = go(sheets=None)
    assert result.rows_added == [] and result.errors == []
    assert len(gmail.sent) == 1


def test_bill_amounts_reach_the_sheet_client_as_decimals():
    _, _, sheets, _ = go()
    ((_, category, bill),) = sheets.calls[0]
    assert category == Category.BILLS and bill.amount == Decimal("5633.0")


# ---- prepare / execute: show the plan, then act on exactly that plan ----


def prepare(gmail=None, models=None, **kwargs):
    gmail = gmail or FakeGmail(EMAILS)
    models = models or Models()
    plan = prepare_daily(
        gmail,
        {},
        DEFAULT_CONFIG,
        models.classifier,
        models.extractor,
        models.summarizer,
        models.group,
        since=SINCE,
        until=UNTIL,
        **kwargs,
    )
    return plan, gmail, models


def test_preparing_the_plan_changes_and_sends_nothing():
    plan, gmail, _ = prepare()
    assert gmail.added == [] and gmail.moved == [] and gmail.sent == []
    assert plan.planned_labels == 3 and plan.planned_rows == 1
    assert plan.rendered.subject.startswith("Inbox digest")


def test_executing_a_plan_acts_on_it_without_asking_the_model_again():
    plan, gmail, models = prepare()
    asked_before = len(models.classified)
    sheets = FakeSheets()
    result = execute_daily(plan, gmail, sheets)
    assert len(models.classified) == asked_before  # no second classification
    assert result.rows_added == ["2"] and len(gmail.sent) == 1
    assert sorted(email_id for email_id, _ in gmail.added) == ["1", "2", "3"]
    assert (
        gmail.sent[0][0] == plan.rendered.subject
    )  # exactly the digest that was shown


def test_executing_without_a_sheets_client_skips_bills_quietly():
    plan, gmail, _ = prepare()
    result = execute_daily(plan, gmail, None)
    assert result.rows_added == [] and result.errors == []


def test_the_plan_remembers_the_inbox_setting_it_was_made_with():
    plan, gmail, _ = prepare(keep_in_inbox=False)
    execute_daily(plan, gmail, FakeSheets())
    assert gmail.added == [] and sorted(i for i, _ in gmail.moved) == ["2", "3"]


def test_each_stage_is_logged_with_its_elapsed_time_and_no_email_text(caplog):
    with caplog.at_level(logging.INFO, logger="gmail_agent.daily"):
        prepare()
    logged = [record.getMessage() for record in caplog.records]
    for stage in ("fetch", "prefilter", "classify", "propose", "extract", "digest"):
        assert any(f"stage {stage}" in line for line in logged), stage
    assert all("s" in line for line in logged)  # elapsed seconds are shown
    text = " ".join(logged)
    for secret in (
        "Interview next week",
        "Statement for October",
        "Weekly reading",
        "@x.com",
    ):
        assert secret not in text


def test_a_stage_that_has_started_is_logged_before_it_finishes(caplog):
    with caplog.at_level(logging.INFO, logger="gmail_agent.daily"):
        prepare()
    logged = [record.getMessage() for record in caplog.records]
    assert logged.index("stage digest started") < logged.index(
        next(line for line in logged if line.startswith("stage digest done"))
    )


# ---- transaction alerts become a table: extracted, never summarised one by one ----

TX_EMAILS = [*EMAILS, email("5", "UPI txn alert")]


def test_a_transaction_alert_becomes_a_table_row_and_is_never_sent_for_summary():
    models = Models()
    gmail = FakeGmail(TX_EMAILS)
    plan = prepare_daily(
        gmail,
        {},
        DEFAULT_CONFIG,
        models.classifier,
        models.extractor,
        models.summarizer,
        models.group,
        since=SINCE,
        until=UNTIL,
        transaction_extractor=models.tx_extractor,
    )
    titles = {s.title: s for s in plan.content.sections}
    spend = titles["Transactions"]
    assert spend.mode == "table" and [r.cells for r in spend.table.rows] == [
        ["INR 50.00", "UPI", "Cafe"]
    ]
    assert "UPI txn alert" not in models.summarized  # a table needs no per-mail summary
    bills = titles["Bills and receipts"]
    assert bills.mode == "table" and bills.table.rows[0].cells[1] == "HDFC Bank"


def test_the_transaction_table_is_in_the_email_that_gets_sent():
    models = Models()
    gmail = FakeGmail(TX_EMAILS)
    result = run_daily(
        gmail,
        None,
        {},
        DEFAULT_CONFIG,
        models.classifier,
        models.extractor,
        models.summarizer,
        models.group,
        since=SINCE,
        until=UNTIL,
        apply=True,
        transaction_extractor=models.tx_extractor,
    )
    assert result.errors == []
    _subject, text, html = gmail.sent[0]
    assert "<table" in html and "1 transaction" in html and "INR 50.00" in html
    assert "1 transaction" in text and "UPI | Cafe" in text
