import re
from types import SimpleNamespace

from langchain_core.runnables import RunnableLambda

from agent.nodes.classify import (
    BATCH_SIZE,
    BODY_CHARS,
    DEFAULT_CONCURRENCY,
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

    def batch(self, inputs, config=None):
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
