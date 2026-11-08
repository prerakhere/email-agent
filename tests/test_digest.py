import re
from datetime import UTC, datetime

from langchain_core.runnables import RunnableLambda

from agent.digest import build_digest
from agent.digest_config import DEFAULT_CONFIG, DigestConfig, DigestSection
from agent.nodes.summarize import GroupText, SummaryBatch, SummaryItem
from agent.schemas import Category, Classification, Email


def make_email(mid, subject="s", received=None) -> Email:
    return Email(
        id=mid,
        thread_id=f"t-{mid}",
        sender=f"Sender <{mid}@x.com>",
        subject=subject,
        body_preview="body",
        received_at=received,
    )


def classified(emails_and_categories):
    emails = [e for e, _ in emails_and_categories]
    classifications = {
        e.id: Classification(category=c, confidence=1.0, reason="r", source="llm")
        for e, c in emails_and_categories
    }
    return emails, classifications


class Chains:
    """Fake summarisers. Records the subjects each one was asked about."""

    def __init__(self):
        self.per_email_subjects: list[str] = []
        self.group_requests: list[dict] = []
        self.per_email = RunnableLambda(self._per_email)
        self.group = RunnableLambda(self._group)

    def _per_email(self, request):
        subjects = re.findall(r"^Subject: (.*)$", request["emails"], re.MULTILINE)
        self.per_email_subjects.extend(subjects)
        return SummaryBatch(
            items=[
                SummaryItem(index=n, summary=f"About {s}.")
                for n, s in enumerate(subjects, start=1)
            ]
        )

    def _group(self, request):
        self.group_requests.append(request)
        return GroupText(summary="A group roundup.")


def digest(pairs, config=DEFAULT_CONFIG, chains=None):
    chains = chains or Chains()
    emails, classifications = classified(pairs)
    return build_digest(
        emails, classifications, config, chains.per_email, chains.group
    ), chains


def test_sections_follow_the_config_order_and_empty_ones_are_left_out():
    pairs = [
        (make_email("1", "news"), Category.NEWSLETTERS),
        (make_email("2", "boss"), Category.IMPORTANT),
    ]
    result, _ = digest(pairs)
    assert [s.title for s in result.sections] == ["Important", "Newsletters"]
    assert result.total == 2


def test_each_email_lands_in_the_section_that_owns_its_category():
    pairs = [
        (make_email("1", "stmt"), Category.BILLS),
        (make_email("2", "order"), Category.RECEIPTS),
    ]
    result, _ = digest(pairs)
    (section,) = result.sections
    assert section.title == "Bills and receipts" and section.count == 2
    # Bills are a table now: with no amounts extracted, both mails are listed as "no amount found",
    # in arrival order, and nothing is sent to the model for them.
    assert section.mode == "table" and section.table.rows == []
    assert [r.email_id for r in section.table.unlisted] == ["1", "2"]


def test_newest_mail_comes_first_and_mail_without_a_date_goes_last():
    pairs = [
        (
            make_email("old", "old", datetime(2026, 11, 6, tzinfo=UTC)),
            Category.IMPORTANT,
        ),
        (make_email("none", "undated"), Category.IMPORTANT),
        (
            make_email("new", "new", datetime(2026, 11, 7, tzinfo=UTC)),
            Category.IMPORTANT,
        ),
    ]
    result, _ = digest(pairs)
    assert [i.email_id for i in result.sections[0].items] == ["new", "old", "none"]


def test_a_per_email_section_summarises_only_max_items_and_counts_the_rest():
    config = DigestConfig(
        sections=[
            DigestSection(title="Important", categories=["important"], max_items=2)
        ]
    )
    pairs = [
        (
            make_email(str(i), f"s{i}", datetime(2026, 11, 7, 12 - i, tzinfo=UTC)),
            Category.IMPORTANT,
        )
        for i in range(5)
    ]
    result, chains = digest(pairs, config)
    section = result.sections[0]
    assert section.count == 5 and section.omitted == 3
    assert [i.email_id for i in section.items] == ["0", "1"]  # the two newest
    assert chains.per_email_subjects == [
        "s0",
        "s1",
    ]  # nothing else was sent to the model


def test_a_group_section_gets_one_summary_and_references_to_the_first_emails():
    config = DigestConfig(
        sections=[
            DigestSection(
                title="Alerts", categories=["job_alerts"], mode="group", max_items=2
            )
        ]
    )
    pairs = [
        (
            make_email(str(i), f"role{i}", datetime(2026, 11, 7, 12 - i, tzinfo=UTC)),
            Category.JOB_ALERTS,
        )
        for i in range(4)
    ]
    result, chains = digest(pairs, config)
    section = result.sections[0]
    assert section.items == [] and section.count == 4
    assert section.group.summary == "A group roundup." and section.group.count == 4
    assert [r.email_id for r in section.refs] == [
        "0",
        "1",
    ]  # newest first, max_items of them
    assert len(chains.group_requests) == 1 and chains.per_email_subjects == []


def test_mail_in_a_category_no_section_covers_is_only_counted():
    config = DigestConfig(
        sections=[DigestSection(title="Important", categories=["important"])]
    )
    pairs = [
        (make_email("1", "boss"), Category.IMPORTANT),
        (make_email("2", "sale"), Category.PROMOTIONS),
        (make_email("3", "ping"), Category.NOTIFICATIONS),
    ]
    result, chains = digest(pairs, config)
    assert result.other_count == 2 and result.total == 3
    assert chains.per_email_subjects == [
        "boss"
    ]  # the uncovered mail never reaches the model


def test_no_mail_means_an_empty_digest_and_no_model_calls():
    result, chains = digest([])
    assert result.sections == [] and result.total == 0 and result.other_count == 0
    assert chains.per_email_subjects == [] and chains.group_requests == []
