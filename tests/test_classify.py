from types import SimpleNamespace

from langchain_core.runnables import RunnableLambda

from agent.nodes.classify import LLMClassification, build_classifier, classify
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


def fake_chain(category: Category, confidence: float, reason: str = "because"):
    """A stand-in for prompt|llm that returns a canned LLM answer (no network)."""
    answer = LLMClassification(category=category, confidence=confidence, reason=reason)
    return RunnableLambda(lambda _inputs: answer)


def test_confident_answer_becomes_llm_classification():
    result = classify(make_email(), fake_chain(Category.PROMOTIONS, 0.92, "sale email"))
    assert result.category == Category.PROMOTIONS
    assert result.confidence == 0.92
    assert result.reason == "sale email"
    assert result.source == "llm"


def test_low_confidence_is_sent_to_needs_review():
    result = classify(make_email(), fake_chain(Category.BILLS, 0.5))
    assert result.category == Category.NEEDS_REVIEW
    assert result.confidence == 0.5
    assert "bills" in result.reason  # keeps what the model originally guessed
    assert result.source == "llm"


def test_confidence_exactly_at_threshold_is_kept():
    result = classify(make_email(), fake_chain(Category.RECEIPTS, 0.7))
    assert result.category == Category.RECEIPTS


def test_custom_threshold_is_respected():
    result = classify(make_email(), fake_chain(Category.RECEIPTS, 0.8), threshold=0.9)
    assert result.category == Category.NEEDS_REVIEW


def test_chain_receives_trimmed_body_and_unsubscribe_hint():
    seen = {}

    def capture(inputs):
        seen.update(inputs)
        return LLMClassification(
            category=Category.PROMOTIONS, confidence=0.9, reason="r"
        )

    email = make_email(body_preview="x" * 2000, list_unsubscribe=True)
    classify(email, RunnableLambda(capture))
    assert len(seen["body_preview"]) == 500
    assert seen["sender"] == "Shop <deals@shop.com>"
    assert seen["subject"] == "50% off today"
    assert seen["has_unsubscribe"] == "yes"


def test_unsubscribe_hint_says_no_when_header_absent():
    seen = {}

    def capture(inputs):
        seen.update(inputs)
        return LLMClassification(
            category=Category.IMPORTANT, confidence=0.9, reason="r"
        )

    classify(make_email(), RunnableLambda(capture))
    assert seen["has_unsubscribe"] == "no"


def test_built_chain_asks_llm_for_structured_output_with_full_prompt():
    captured = {}

    def fake_structured(prompt_value):
        captured["text"] = prompt_value.to_string()
        return LLMClassification(
            category=Category.PROMOTIONS, confidence=0.9, reason="r"
        )

    def with_structured_output(schema):
        captured["schema"] = schema
        return RunnableLambda(fake_structured)

    fake_llm = SimpleNamespace(with_structured_output=with_structured_output)
    chain = build_classifier(fake_llm)
    classify(make_email(), chain)

    assert captured["schema"] is LLMClassification
    text = captured["text"]
    assert "deals@shop.com" in text
    assert "50% off today" in text
    assert "Big sale" in text
    for category in Category:
        assert category.value in text  # model is told every allowed category
