import re
from types import SimpleNamespace

import httpx
import openai
from langchain_core.runnables import RunnableLambda

from agent.digest_config import DigestSection
from agent.nodes.summarize import (
    EMAILS_PER_REQUEST,
    GROUP_BODY_CHARS,
    MAX_GROUP_EMAILS,
    GroupText,
    SummaryBatch,
    SummaryItem,
    build_group_summarizer,
    build_summarizer,
    summarize_emails,
    summarize_group,
)
from agent.schemas import Category, Email


def make_email(**kwargs) -> Email:
    defaults = {
        "id": "m1",
        "thread_id": "t1",
        "sender": "Recruiter <jane@corp.com>",
        "subject": "Interview next week",
        "body_preview": "Can you do Tuesday 3pm?",
    }
    return Email(**{**defaults, **kwargs})


def make_section(**kwargs) -> DigestSection:
    defaults = {
        "title": "Important",
        "categories": [Category.IMPORTANT],
        "style": "List the action points.",
    }
    return DigestSection(**{**defaults, **kwargs})


def item(index, summary="A summary.", points=()) -> SummaryItem:
    return SummaryItem(index=index, summary=summary, action_points=list(points))


class FakeModel:
    """Stands in for prompt|llm: summarises each email by its subject and records requests."""

    def __init__(self, points=()):
        self.requests: list[dict] = []
        self._points = points
        self.runnable = RunnableLambda(self._invoke)

    def _invoke(self, request):
        self.requests.append(request)
        subjects = re.findall(r"^Subject: (.*)$", request["emails"], re.MULTILINE)
        return SummaryBatch(
            items=[
                item(n, f"About {subject}.", self._points)
                for n, subject in enumerate(subjects, start=1)
            ]
        )


def test_each_email_gets_its_summary_in_order_with_its_details():
    model = FakeModel(points=["Reply by Friday"])
    emails = [
        make_email(id="a", subject="First", sender="A <a@x.com>"),
        make_email(id="b", subject="Second"),
    ]
    first, second = summarize_emails(emails, make_section(), model.runnable)
    assert (first.email_id, first.subject, first.sender) == (
        "a",
        "First",
        "A <a@x.com>",
    )
    assert first.summary == "About First."
    assert first.action_points == ["Reply by Friday"]
    assert second.email_id == "b" and second.fallback is False


def test_the_request_carries_the_section_style_and_numbered_blocks():
    model = FakeModel()
    section = make_section(style="Focus on deadlines.")
    summarize_emails(
        [make_email(subject="One"), make_email(subject="Two")], section, model.runnable
    )
    (request,) = model.requests
    assert request["style"] == "Focus on deadlines."
    assert "<email id=1>" in request["emails"] and "<email id=2>" in request["emails"]
    assert request["emails"].count("</email>") == 2


def test_the_model_sees_redacted_text_but_the_real_sender():
    model = FakeModel()
    email = make_email(
        sender="Bank <alerts@bank.com>",
        subject="Your OTP is 4821",
        body_preview="Card 4111 1111 1111 1111 see https://bank.com/x?t=1",
    )
    summarize_emails([email], make_section(), model.runnable)
    text = model.requests[0]["emails"]
    assert "From: Bank <alerts@bank.com>" in text
    assert "Subject: Your OTP is [REDACTED]" in text
    assert "Card [NUMBER] see [LINK:bank.com]" in text
    assert "4111" not in text


def test_the_section_decides_how_much_of_the_body_is_read():
    model = FakeModel()
    email = make_email(body_preview="x" * 2000)
    summarize_emails([email], make_section(body_chars=300), model.runnable)
    text = model.requests[0]["emails"]
    assert "x" * 300 in text and "x" * 301 not in text


def test_five_emails_per_request_by_default():
    assert EMAILS_PER_REQUEST == 5
    model = FakeModel()
    emails = [make_email(id=str(i), subject=f"s{i}") for i in range(12)]
    results = summarize_emails(emails, make_section(), model.runnable)
    assert sorted(r["emails"].count("<email id=") for r in model.requests) == [2, 5, 5]
    assert [r.summary for r in results] == [f"About s{i}." for i in range(12)]


def test_a_skipped_email_falls_back_to_its_subject_and_is_flagged():
    def reply(_request):
        return SummaryBatch(items=[item(1, "Good."), item(3, "Also good.")])

    emails = [make_email(id=s, subject=f"subj-{s}") for s in "abc"]
    first, second, third = summarize_emails(
        emails, make_section(), RunnableLambda(reply)
    )
    assert first.summary == "Good." and not first.fallback
    assert second.fallback and second.summary == "subj-b"
    assert third.summary == "Also good."


def test_blank_summaries_and_bad_indexes_are_not_trusted():
    def reply(_request):
        return SummaryBatch(
            items=[item(1, "   "), item(1, "dup"), item(9, "ghost"), item(0, "zero")]
        )

    (only,) = summarize_emails(
        [make_email(subject="Real")], make_section(), RunnableLambda(reply)
    )
    assert only.fallback and only.summary == "Real"


def test_a_content_filter_rejection_falls_back_for_that_email_only():
    def filtered(request):
        if "BADTEXT" in request["emails"]:
            response = httpx.Response(
                400, request=httpx.Request("POST", "https://example.invalid/")
            )
            raise openai.BadRequestError(
                "rejected", response=response, body={"code": "content_filter"}
            )
        subjects = re.findall(r"^Subject: (.*)$", request["emails"], re.MULTILINE)
        return SummaryBatch(items=[item(n, "ok.") for n in range(1, len(subjects) + 1)])

    emails = [
        make_email(id="a", subject="A"),
        make_email(id="b", subject="B", body_preview="BADTEXT"),
    ]
    good, blocked = summarize_emails(emails, make_section(), RunnableLambda(filtered))
    assert good.summary == "ok." and not good.fallback
    assert blocked.fallback and blocked.summary == "B"


def test_links_written_by_the_model_are_removed():
    def reply(_request):
        return SummaryBatch(
            items=[
                item(
                    1,
                    "Pay now at https://evil.example/pay?x=1 or www.evil.example today.",
                    ["Click http://evil.example/a to confirm", "Reply to Jane"],
                )
            ]
        )

    (only,) = summarize_emails([make_email()], make_section(), RunnableLambda(reply))
    assert "evil" not in only.summary and "http" not in only.summary
    assert only.summary.startswith("Pay now at")
    assert all("evil" not in p for p in only.action_points)
    assert "Reply to Jane" in only.action_points


def test_action_points_are_capped_in_number_and_length():
    long_point = "word " * 100
    points = [long_point] + [f"point {i}" for i in range(10)]

    def reply(_request):
        return SummaryBatch(items=[item(1, "Fine.", points)])

    (only,) = summarize_emails([make_email()], make_section(), RunnableLambda(reply))
    assert len(only.action_points) == 5
    assert all(len(p) <= 200 for p in only.action_points)


def test_no_emails_means_no_model_call():
    class Exploding:
        def batch(self, *_a, **_k):
            raise AssertionError("must not be called")

    assert summarize_emails([], make_section(), Exploding()) == []


def test_the_built_chain_asks_for_the_summary_shape_with_the_full_prompt():
    captured = {}

    def fake_structured(prompt_value):
        captured["text"] = prompt_value.to_string()
        return SummaryBatch(items=[item(1, "ok.")])

    def with_structured_output(schema):
        captured["schema"] = schema
        return RunnableLambda(fake_structured)

    chain = build_summarizer(
        SimpleNamespace(with_structured_output=with_structured_output)
    )
    summarize_emails([make_email()], make_section(style="Be brief."), chain)
    assert captured["schema"] is SummaryBatch
    text = captured["text"].lower()
    assert "be brief." in text  # the section's style reaches the model
    assert "untrusted" in text  # emails are data, not instructions
    assert "one short sentence" in text  # next-day review: one line at most
    assert "two sentences" not in text
    assert "never write" in text and "link" in text  # no model-written URLs


# ---- group sections: one short paragraph for the whole group ----


def group_section(**kwargs) -> DigestSection:
    defaults = {
        "title": "Job alerts",
        "categories": [Category.JOB_ALERTS],
        "style": "Count and top roles.",
        "mode": "group",
        "max_items": 5,
    }
    return DigestSection(**{**defaults, **kwargs})


class FakeGroupModel:
    """Summarises a group by listing the subjects it was given; records each request."""

    def __init__(self):
        self.requests: list[dict] = []
        self.runnable = RunnableLambda(self._invoke)

    def _invoke(self, request):
        self.requests.append(request)
        subjects = re.findall(r"^Subject: (.*)$", request["emails"], re.MULTILINE)
        return GroupText(summary="Seen: " + ", ".join(subjects) + ".")


def group_emails(n, **kwargs):
    return [make_email(id=str(i), subject=f"role{i}", **kwargs) for i in range(n)]


def test_a_group_gets_one_summary_and_our_own_count():
    model = FakeGroupModel()
    result = summarize_group(group_emails(3), group_section(), model.runnable)
    assert result.count == 3 and result.fallback is False
    assert result.summary == "Seen: role0, role1, role2."
    assert len(model.requests) == 1


def test_the_group_request_carries_style_limits_and_compact_blocks():
    model = FakeGroupModel()
    emails = group_emails(2, body_preview="x" * 2000)
    summarize_group(
        emails, group_section(style="Name the top roles.", max_items=3), model.runnable
    )
    (request,) = model.requests
    assert request["style"] == "Name the top roles."
    assert request["max_items"] == 3 and request["count"] == 2
    assert GROUP_BODY_CHARS == 600
    assert "x" * 600 in request["emails"] and "x" * 601 not in request["emails"]
    assert "<email id=1>" in request["emails"] and "<email id=2>" in request["emails"]


def test_a_short_section_body_size_is_never_exceeded():
    model = FakeGroupModel()
    summarize_group(
        group_emails(1, body_preview="x" * 2000),
        group_section(body_chars=300),
        model.runnable,
    )
    assert "x" * 300 in model.requests[0]["emails"]
    assert "x" * 301 not in model.requests[0]["emails"]


def test_only_the_first_forty_are_sent_but_the_count_is_the_true_total():
    model = FakeGroupModel()
    result = summarize_group(group_emails(55), group_section(), model.runnable)
    assert MAX_GROUP_EMAILS == 40
    assert model.requests[0]["emails"].count("<email id=") == 40
    assert result.count == 55


def test_links_in_a_group_summary_are_removed():
    reply = RunnableLambda(
        lambda _r: GroupText(summary="Top: Dev at Acme https://evil.example/x.")
    )
    result = summarize_group(group_emails(2), group_section(), reply)
    assert "http" not in result.summary and "evil" not in result.summary
    assert result.summary.startswith("Top: Dev at Acme")


def test_a_blank_group_summary_is_a_fallback_not_an_invention():
    reply = RunnableLambda(lambda _r: GroupText(summary="  "))
    result = summarize_group(group_emails(2), group_section(), reply)
    assert result.fallback is True and result.summary == "" and result.count == 2


def content_filter_error():
    response = httpx.Response(
        400, request=httpx.Request("POST", "https://example.invalid/")
    )
    return openai.BadRequestError(
        "rejected", response=response, body={"code": "content_filter"}
    )


def test_a_content_filter_rejection_is_split_until_the_bad_email_is_isolated():
    def filtered(request):
        if "BADTEXT" in request["emails"]:
            raise content_filter_error()
        subjects = re.findall(r"^Subject: (.*)$", request["emails"], re.MULTILINE)
        return GroupText(summary="Seen: " + ", ".join(subjects) + ".")

    emails = group_emails(4)
    emails[2] = make_email(id="2", subject="role2", body_preview="BADTEXT")
    result = summarize_group(emails, group_section(), RunnableLambda(filtered))
    assert result.fallback is False and result.count == 4
    for clean in ("role0", "role1", "role3"):
        assert clean in result.summary
    assert "role2" not in result.summary


def test_when_everything_is_blocked_the_group_falls_back():
    def always(_request):
        raise content_filter_error()

    result = summarize_group(group_emails(3), group_section(), RunnableLambda(always))
    assert result.fallback is True and result.summary == "" and result.count == 3


def test_other_errors_in_a_group_are_raised():
    def boom(_request):
        raise RuntimeError("rate limit exhausted")

    try:
        summarize_group(group_emails(2), group_section(), RunnableLambda(boom))
    except RuntimeError as error:
        assert "rate limit exhausted" in str(error)
    else:
        raise AssertionError("the error was swallowed")


def test_an_empty_group_makes_no_model_call():
    model = FakeGroupModel()
    result = summarize_group([], group_section(), model.runnable)
    assert result.count == 0 and result.summary == "" and not result.fallback
    assert model.requests == []


def test_the_group_chain_asks_for_the_group_shape_with_the_full_prompt():
    captured = {}

    def fake_structured(prompt_value):
        captured["text"] = prompt_value.to_string()
        return GroupText(summary="ok.")

    def with_structured_output(schema):
        captured["schema"] = schema
        return RunnableLambda(fake_structured)

    chain = build_group_summarizer(
        SimpleNamespace(with_structured_output=with_structured_output)
    )
    summarize_group(group_emails(2), group_section(style="Be brief."), chain)
    assert captured["schema"] is GroupText
    text = captured["text"].lower()
    assert "be brief." in text and "untrusted" in text
    assert "never write" in text and "link" in text
    assert "at most 5" in text  # the section's max_items


def test_a_group_paragraph_is_one_short_sentence():
    from agent.nodes.summarize import GROUP_SYSTEM_PROMPT

    text = GROUP_SYSTEM_PROMPT.lower()
    assert "one short sentence" in text and "three sentences" not in text
