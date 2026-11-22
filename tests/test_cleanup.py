"""The clean-up list: promotions that could go to the bin once the owner approves. This step picks
them and writes a short summary of each (shown later on the approval page, with a checkbox per
email); the digest itself only says how many there are. Nothing is moved here."""

import re
from datetime import UTC, datetime

from langchain_core.runnables import RunnableLambda

from agent.cleanup import (
    CLEANUP_SECTION,
    MAX_CLEANUP_ITEMS,
    CleanupItem,
    CleanupList,
    build_cleanup,
)
from agent.digest import DigestContent
from agent.digest_email import render_digest
from agent.nodes.summarize import SummaryBatch, SummaryItem
from agent.schemas import Category, Email, Proposal

SINCE = datetime(2026, 11, 7, 0, 30, tzinfo=UTC)
UNTIL = datetime(2026, 11, 8, 0, 30, tzinfo=UTC)


def make_email(mid):
    return Email(
        id=mid,
        thread_id=f"t-{mid}",
        sender=f"Shop {mid} <deals{mid}@shop.example>",
        subject=f"Offer {mid}",
        body_preview="20% off everything until Sunday.",
    )


def proposal(mid, category=Category.PROMOTIONS, starred=False):
    e = make_email(mid)
    return Proposal(
        email_id=mid,
        sender=e.sender,
        subject=e.subject,
        category=category,
        label="Agent/Promotions",
        confidence=0.9,
        reason="r",
        source="llm",
        starred=starred,
    )


class Summarizer:
    """Fake summariser: 'About <subject>.' for each email; records every request."""

    def __init__(self, skip=()):
        self.requests: list[dict] = []
        self._skip = set(skip)
        self.runnable = RunnableLambda(self._invoke)

    def _invoke(self, request):
        self.requests.append(request)
        subjects = re.findall(r"^Subject: (.*)$", request["emails"], re.MULTILINE)
        return SummaryBatch(
            items=[
                SummaryItem(index=n, summary=f"About {s}.")
                for n, s in enumerate(subjects, start=1)
                if s not in self._skip
            ]
        )

    def subjects(self):
        return [
            s
            for r in self.requests
            for s in re.findall(r"^Subject: (.*)$", r["emails"], re.MULTILINE)
        ]


def build(proposals, summarizer=None):
    summarizer = summarizer or Summarizer()
    emails = [make_email(p.email_id) for p in proposals]
    return build_cleanup(proposals, emails, summarizer.runnable), summarizer


def test_only_promotions_are_offered_for_clean_up():
    found, summarizer = build(
        [
            proposal("1"),
            proposal("2", category=Category.NEWSLETTERS),
            proposal("3", category=Category.IMPORTANT),
            proposal("4", category=Category.NEEDS_REVIEW),
            proposal("5", category=Category.BILLS),
        ]
    )
    assert found.email_ids == ["1"]
    assert summarizer.subjects() == ["Offer 1"]  # only the offered mail is summarised


def test_starred_promotions_are_never_offered():
    found, _ = build([proposal("1", starred=True), proposal("2")])
    assert found.email_ids == ["2"]


def test_nothing_to_clean_gives_no_list_and_no_model_call():
    found, summarizer = build([proposal("1", category=Category.NEWSLETTERS)])
    assert found is None
    assert summarizer.requests == []


def test_every_offered_email_is_listed_with_sender_subject_and_summary_in_order():
    found, _ = build([proposal("1"), proposal("2"), proposal("3")])
    assert found.items == [
        CleanupItem(
            email_id=mid,
            sender=f"Shop {mid} <deals{mid}@shop.example>",
            subject=f"Offer {mid}",
            summary=f"About Offer {mid}.",
        )
        for mid in ("1", "2", "3")
    ]


def test_the_summaries_are_asked_for_in_the_clean_up_style():
    _, summarizer = build([proposal("1")])
    assert summarizer.requests[0]["style"] == CLEANUP_SECTION.style
    assert "offer" in CLEANUP_SECTION.style.lower()


def test_an_email_the_model_skipped_falls_back_to_its_subject():
    found, _ = build([proposal("1")], Summarizer(skip={"Offer 1"}))
    assert found.items[0].summary == "Offer 1"


def test_a_heavy_day_is_capped():
    found, summarizer = build([proposal(str(n)) for n in range(MAX_CLEANUP_ITEMS + 5)])
    assert found.count == MAX_CLEANUP_ITEMS
    assert len(summarizer.subjects()) == MAX_CLEANUP_ITEMS


def render(cleanup):
    content = DigestContent(sections=[], other_count=0, total=5, cleanup=cleanup)
    return render_digest(content, SINCE, UNTIL)


def items(n):
    return [
        CleanupItem(
            email_id=str(i), sender="S <s@x.example>", subject=f"Offer {i}", summary="s"
        )
        for i in range(n)
    ]


def test_the_digest_ends_with_the_clean_up_count_only():
    rendered = render(CleanupList(items=items(23)))
    for body in (rendered.html, rendered.text):
        assert "Clean-up" in body
        assert "23 promotions ready for the bin" in body
        assert "Offer 0" not in body  # the list itself lives on the approval page
    assert rendered.html.rindex("Clean-up") > rendered.html.index("Inbox digest</h1>")


def test_one_email_reads_in_the_singular():
    assert "1 promotion ready for the bin" in render(CleanupList(items=items(1))).text


def test_without_a_clean_up_list_there_is_no_clean_up_block():
    rendered = render(None)
    assert "Clean-up" not in rendered.html and "Clean-up" not in rendered.text
