import re
from datetime import UTC, datetime

from langchain_core.runnables import RunnableLambda

from agent.digest_config import DEFAULT_CONFIG
from agent.digest_run import create_digest
from agent.nodes.classify import LLMBatch, LLMItem
from agent.nodes.summarize import GroupText, SummaryBatch, SummaryItem
from agent.profile import Profile
from agent.schemas import Category, Email

SINCE = datetime(2026, 11, 7, 2, 30, tzinfo=UTC)
UNTIL = datetime(2026, 11, 8, 2, 30, tzinfo=UTC)


class FakeGmail:
    def __init__(self, emails, label_ids):
        self._emails = emails
        self._label_ids = label_ids
        self.since_args = None

    def fetch_since(self, since, max_results=500):
        self.since_args = (since, max_results)
        return self._emails

    def label_ids_by_name(self):
        return self._label_ids

    def list_label_names(self):
        return list(self._label_ids)


def subjects_in(request):
    return re.findall(r"^Subject: (.*)$", request["emails"], re.MULTILINE)


def classifier(request):
    """Calls anything starting with 'Interview' important, everything else a newsletter."""
    items = []
    for n, subject in enumerate(subjects_in(request), start=1):
        category = (
            Category.IMPORTANT
            if subject.startswith("Interview")
            else Category.NEWSLETTERS
        )
        items.append(LLMItem(index=n, category=category, confidence=0.95, reason="r"))
    return LLMBatch(items=items)


def summarizer(request):
    return SummaryBatch(
        items=[
            SummaryItem(index=n, summary=f"Summary of {s}.")
            for n, s in enumerate(subjects_in(request), start=1)
        ]
    )


def group(_request):
    return GroupText(summary="Several relevant roles.")


def email(mid, subject, labels=("INBOX",)):
    return Email(
        id=mid,
        thread_id=f"t-{mid}",
        sender=f"S <{mid}@x.com>",
        subject=subject,
        body_preview="body",
        label_ids=list(labels),
    )


def make_digest(emails, gmail=None):
    gmail = gmail or FakeGmail(emails, {"Agent/Job-Alerts": "L_jobs"})
    content, rendered = create_digest(
        gmail,
        {},
        DEFAULT_CONFIG,
        RunnableLambda(classifier),
        RunnableLambda(summarizer),
        RunnableLambda(group),
        since=SINCE,
        until=UNTIL,
        profile=Profile(
            timezone="Asia/Kolkata"
        ),  # the expected times below are Indian time
    )
    return content, rendered, gmail


def test_mail_from_the_window_ends_up_in_the_right_sections_of_the_email():
    emails = [
        email("1", "Interview next week"),
        email("2", "Weekly reading"),
        email(
            "3", "5 new jobs", labels=("INBOX", "L_jobs")
        ),  # already labelled: no model call
    ]
    content, rendered, _ = make_digest(emails)
    assert [s.title for s in content.sections] == [
        "Important",
        "Job Alerts",
        "Newsletters",
    ]
    assert "Summary of Interview next week." in rendered.html
    assert "Several relevant roles." in rendered.html
    assert "Summary of Weekly reading." in rendered.html
    assert "3 emails" in rendered.subject


def test_the_window_start_is_what_gets_fetched_and_what_the_email_shows():
    _, rendered, gmail = make_digest([email("1", "Interview")])
    assert gmail.since_args == (SINCE, 500)
    assert "7 Nov, 8:00 AM" in rendered.text and "8 Nov, 8:00 AM" in rendered.text


def test_an_empty_window_still_produces_an_email_that_says_so():
    content, rendered, _ = make_digest([])
    assert content.total == 0
    assert "No new mail" in rendered.text
