import re
from types import SimpleNamespace

import httpx
import openai
import pytest
from langchain_core.runnables import RunnableLambda

from agent.nodes.classify import (
    BATCH_SIZE,
    BODY_CHARS,
    DEFAULT_CONCURRENCY,
    SYSTEM_PROMPT,
    LLMBatch,
    LLMItem,
    build_classifier,
    classify_many,
)
from agent.schemas import Category, Email


def make_email(**kwargs) -> Email:
    defaults = {
        "id": "m1",
        "thread_id": "t1",
        "sender": "Shop <deals@shop.com>",
        "subject": "50% off today",
        "body_preview": "Big sale",
    }
    return Email(**{**defaults, **kwargs})


def item(index, category, confidence=0.9, reason="r") -> LLMItem:
    return LLMItem(index=index, category=category, confidence=confidence, reason=reason)


class FakeModel:
    """Stands in for prompt|llm. Answers by the subject it finds in the request text and
    records every request, so tests can see exactly what would be sent."""

    def __init__(self, answers=None, default=(Category.PROMOTIONS, 0.9)):
        self.requests: list[str] = []
        self._answers = answers or {}
        self._default = default
        self.runnable = RunnableLambda(self._invoke)

    def _invoke(self, inputs):
        text = inputs["emails"]
        self.requests.append(text)
        subjects = re.findall(r"^Subject: (.*)$", text, re.MULTILINE)
        items = []
        for n, subject in enumerate(subjects, start=1):
            category, confidence = self._answers.get(subject, self._default)
            items.append(item(n, category, confidence))
        return LLMBatch(items=items)


def test_answers_come_back_in_email_order_marked_as_llm():
    model = FakeModel(
        {
            "a": (Category.BILLS, 0.95),
            "b": (Category.PROMOTIONS, 0.9),
            "c": (Category.NEWSLETTERS, 0.8),
        }
    )
    emails = [make_email(id=s, subject=s) for s in "abc"]
    results = classify_many(emails, model.runnable)
    assert [r.category for r in results] == [
        Category.BILLS,
        Category.PROMOTIONS,
        Category.NEWSLETTERS,
    ]
    assert [r.confidence for r in results] == [0.95, 0.9, 0.8]
    assert all(r.source == "llm" for r in results)


def test_low_confidence_goes_to_needs_review_and_keeps_the_original_guess():
    model = FakeModel({"unsure": (Category.BILLS, 0.5), "sure": (Category.BILLS, 0.9)})
    emails = [make_email(subject="sure"), make_email(subject="unsure")]
    sure, unsure = classify_many(emails, model.runnable)
    assert sure.category == Category.BILLS
    assert unsure.category == Category.NEEDS_REVIEW
    assert unsure.confidence == 0.5
    assert "bills" in unsure.reason


def test_confidence_exactly_at_the_threshold_is_kept():
    model = FakeModel(default=(Category.RECEIPTS, 0.7))
    (result,) = classify_many([make_email()], model.runnable)
    assert result.category == Category.RECEIPTS


def test_a_custom_threshold_is_respected():
    model = FakeModel(default=(Category.RECEIPTS, 0.8))
    (result,) = classify_many([make_email()], model.runnable, threshold=0.9)
    assert result.category == Category.NEEDS_REVIEW


def test_many_emails_are_split_into_requests_of_the_batch_size():
    assert BATCH_SIZE == 10
    model = FakeModel(
        {
            f"s{i}": (Category.BILLS if i % 2 else Category.NEWSLETTERS, 0.9)
            for i in range(25)
        }
    )
    emails = [make_email(id=str(i), subject=f"s{i}") for i in range(25)]
    results = classify_many(emails, model.runnable)
    assert sorted(r.count("<email id=") for r in model.requests) == [5, 10, 10]
    assert [r.category for r in results] == [
        Category.BILLS if i % 2 else Category.NEWSLETTERS for i in range(25)
    ]


def test_the_batch_size_is_configurable():
    model = FakeModel()
    emails = [make_email(id=str(i), subject=f"s{i}") for i in range(7)]
    classify_many(emails, model.runnable, batch_size=3)
    assert sorted(r.count("<email id=") for r in model.requests) == [1, 3, 3]


def test_each_email_is_in_its_own_numbered_block():
    model = FakeModel()
    emails = [make_email(subject="first"), make_email(subject="second")]
    classify_many(emails, model.runnable)
    (text,) = model.requests
    assert "<email id=1>" in text and "<email id=2>" in text
    assert text.count("</email>") == 2
    assert text.index("first") < text.index("second")


def test_an_email_the_model_skipped_becomes_needs_review_without_crashing():
    def reply(_inputs):
        return LLMBatch(items=[item(1, Category.BILLS), item(3, Category.NEWSLETTERS)])

    emails = [make_email(subject=s) for s in ("a", "b", "c")]
    first, second, third = classify_many(emails, RunnableLambda(reply))
    assert first.category == Category.BILLS
    assert second.category == Category.NEEDS_REVIEW
    assert "no answer" in second.reason
    assert third.category == Category.NEWSLETTERS


def test_unknown_and_duplicate_indexes_are_ignored_first_answer_wins():
    def reply(_inputs):
        return LLMBatch(
            items=[
                item(1, Category.BILLS),
                item(1, Category.PROMOTIONS),  # duplicate: ignored
                item(99, Category.IMPORTANT),  # no such email: ignored
                item(0, Category.IMPORTANT),  # ids start at 1: ignored
            ]
        )

    emails = [make_email(subject="a"), make_email(subject="b")]
    first, second = classify_many(emails, RunnableLambda(reply))
    assert first.category == Category.BILLS
    assert second.category == Category.NEEDS_REVIEW


def test_requests_carry_redacted_subject_and_body_but_the_real_sender():
    model = FakeModel()
    email = make_email(
        sender="Bank <alerts@bank.com>",
        subject="Your OTP is 4821",
        body_preview="Card 4111 1111 1111 1111 see https://bank.com/x?t=1",
    )
    classify_many([email], model.runnable)
    (text,) = model.requests
    assert "From: Bank <alerts@bank.com>" in text
    assert "Subject: Your OTP is [REDACTED]" in text
    assert "Card [NUMBER] see [LINK:bank.com]" in text
    assert "4111" not in text and "4821" not in text


def test_the_body_is_trimmed_and_the_unsubscribe_hint_is_included():
    model = FakeModel()
    email = make_email(body_preview="x" * 2000, list_unsubscribe=True)
    classify_many([email], model.runnable)
    (text,) = model.requests
    assert BODY_CHARS == 500
    assert "x" * 500 in text and "x" * 501 not in text
    assert "Has unsubscribe header: yes" in text
    model = FakeModel()
    classify_many([make_email()], model.runnable)
    assert "Has unsubscribe header: no" in model.requests[0]


class RecordingChain:
    """Records how it was asked to run its requests, to check the concurrency cap."""

    def __init__(self):
        self.config = None

    def batch(self, inputs, config=None, **_kwargs):
        self.config = config
        return [LLMBatch(items=[item(1, Category.PROMOTIONS)]) for _ in inputs]


def test_the_number_of_requests_in_flight_is_capped():
    chain = RecordingChain()
    classify_many([make_email()], chain, max_concurrency=3)
    assert chain.config == {"max_concurrency": 3}


def test_the_default_cap_is_small_enough_for_a_low_rate_limit():
    chain = RecordingChain()
    classify_many([make_email()], chain)
    assert chain.config == {"max_concurrency": DEFAULT_CONCURRENCY}
    assert DEFAULT_CONCURRENCY == 2


def test_no_emails_means_the_chain_is_never_called():
    class Exploding:
        def batch(self, *_a, **_k):
            raise AssertionError("chain must not be called")

    assert classify_many([], Exploding()) == []


def test_built_chain_asks_the_model_for_the_batch_shape_with_the_full_prompt():
    captured = {}

    def fake_structured(prompt_value):
        captured["text"] = prompt_value.to_string()
        return LLMBatch(items=[item(1, Category.PROMOTIONS)])

    def with_structured_output(schema):
        captured["schema"] = schema
        return RunnableLambda(fake_structured)

    chain = build_classifier(
        SimpleNamespace(with_structured_output=with_structured_output)
    )
    classify_many([make_email()], chain)

    assert captured["schema"] is LLMBatch
    text = captured["text"]
    assert "deals@shop.com" in text and "50% off today" in text and "Big sale" in text
    for category in Category:
        assert category.value in text  # the model is told every allowed category
    assert (
        "untrusted" in text.lower()
    )  # emails must be treated as data, not instructions


def bad_request(code):
    """The error Azure raises for a rejected request (HTTP 400 with an error code)."""
    response = httpx.Response(
        400, request=httpx.Request("POST", "https://example.invalid/")
    )
    return openai.BadRequestError(
        "rejected", response=response, body={"code": code, "message": "rejected"}
    )


def filtered_unless_clean(inputs):
    """A model that rejects any request containing BADTEXT, like Azure's content filter."""
    text = inputs["emails"]
    if "BADTEXT" in text:
        raise bad_request("content_filter")
    subjects = re.findall(r"^Subject: (.*)$", text, re.MULTILINE)
    return LLMBatch(
        items=[item(n, Category.NEWSLETTERS) for n in range(1, len(subjects) + 1)]
    )


def test_a_rejected_batch_is_retried_one_email_at_a_time():
    emails = [
        make_email(subject="a"),
        make_email(subject="b", body_preview="BADTEXT"),
        make_email(subject="c"),
    ]
    first, second, third = classify_many(emails, RunnableLambda(filtered_unless_clean))
    assert first.category == Category.NEWSLETTERS
    assert third.category == Category.NEWSLETTERS
    assert second.category == Category.NEEDS_REVIEW
    assert "content filter" in second.reason
    assert second.source == "llm"


def test_only_the_rejected_batch_is_retried_other_batches_are_left_alone():
    requests = []

    def record_then_filter(inputs):
        requests.append(inputs["emails"].count("<email id="))
        return filtered_unless_clean(inputs)

    emails = [make_email(subject=f"s{i}") for i in range(12)]
    emails[3] = make_email(subject="s3", body_preview="BADTEXT")
    results = classify_many(emails, RunnableLambda(record_then_filter))
    assert [r.category for r in results].count(Category.NEEDS_REVIEW) == 1
    assert results[3].category == Category.NEEDS_REVIEW
    # first batch (10) rejected, then its 10 emails one by one; the second batch (2) went through once
    assert sorted(requests) == [1] * 10 + [2, 10]


def test_other_errors_are_not_swallowed():
    def boom(_inputs):
        raise RuntimeError("rate limit exhausted")

    with pytest.raises(RuntimeError, match="rate limit exhausted"):
        classify_many([make_email()], RunnableLambda(boom))


def test_a_400_that_is_not_a_content_filter_is_not_swallowed():
    def other_400(_inputs):
        raise bad_request("invalid_request_error")

    with pytest.raises(openai.BadRequestError):
        classify_many([make_email()], RunnableLambda(other_400))


# ---- guidance that separates look-alike mail ----


def test_a_single_payment_alert_is_a_transaction_but_a_statement_is_a_bill():
    text = SYSTEM_PROMPT.lower()
    assert "transactions:" in text and "upi" in text and "card" in text
    assert "statement" in text and "bill is due" in text
    assert "not a bill" in text  # an alert about one payment is not a bill


def test_declined_or_failed_payment_attempts_are_notifications_not_transactions():
    # The user acts on these at once, so by the next day they are stale: a one-line roundup at most.
    text = SYSTEM_PROMPT.lower()
    assert "declined, rejected or failed" in text
    assert "notifications" in text


def test_lender_marketing_is_a_promotion_even_when_it_reads_like_account_news():
    text = SYSTEM_PROMPT.lower()
    assert "emi" in text and "limit" in text
    assert "bill needs" in text  # a bill needs a specific amount due or a payment made


# ---- the digest is a next-day review: automated and real-time mail is stale, not important ----


def test_automated_account_security_and_verification_mail_is_a_notification_not_important():
    text = SYSTEM_PROMPT.lower()
    assert "automated account" in text and "security" in text and "sign-in" in text
    assert "verification" in text and "one-time" in text and "welcome" in text
    assert "even from banks, google or microsoft" in text
    assert "never important" in text  # automated notices are never important


def test_shipping_and_delivery_updates_are_notifications():
    text = SYSTEM_PROMPT.lower()
    assert "out for delivery" in text and "delivered" in text
    assert "stale by the next day" in text


def test_booking_and_ticket_confirmations_are_receipts():
    text = SYSTEM_PROMPT.lower()
    assert "booking" in text and "ticket" in text and "bus, train, flight" in text


def test_festival_greetings_and_fundraising_appeals_are_promotions_not_newsletters():
    text = SYSTEM_PROMPT.lower()
    assert "greetings" in text and "fundraising" in text


def test_only_mail_written_by_a_real_person_gets_the_benefit_of_the_doubt_for_important():
    text = SYSTEM_PROMPT.lower()
    assert "written by a real person matters, choose important" in text
