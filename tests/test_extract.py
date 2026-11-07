from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from langchain_core.runnables import RunnableLambda

from agent.nodes.extract import (
    BODY_CHARS,
    LLMBill,
    build_bill_inputs,
    build_extractor,
    extract_bill,
)
from agent.schemas import Email


def make_email(**kwargs) -> Email:
    defaults = {
        "id": "m1",
        "thread_id": "t1",
        "sender": "HDFC Bank <statements@hdfcbank.net>",
        "subject": "Your credit card statement",
        "body_preview": "Total amount due Rs 12500.00 by 5 Dec",
    }
    return Email(**{**defaults, **kwargs})


def llm_bill(**kwargs) -> LLMBill:
    defaults = {
        "vendor": "HDFC Bank",
        "amount": 12500.0,
        "currency": "inr",
        "due_date": date(2026, 12, 5),
        "confidence": 0.9,
    }
    return LLMBill(**{**defaults, **kwargs})


def chain_returning(answer: LLMBill):
    seen: list[dict] = []

    def invoke(inputs):
        seen.append(inputs)
        return answer

    chain = RunnableLambda(invoke)
    chain.seen = seen  # type: ignore[attr-defined]
    return chain


def test_answer_becomes_a_bill_with_decimal_amount_and_upper_case_currency():
    bill = extract_bill(make_email(), chain_returning(llm_bill()))
    assert bill is not None
    assert bill.vendor == "HDFC Bank"
    assert bill.amount == Decimal("12500.0")
    assert bill.currency == "INR"
    assert bill.due_date == date(2026, 12, 5)
    assert bill.confidence == 0.9


def test_missing_due_date_is_allowed_for_receipts():
    bill = extract_bill(make_email(), chain_returning(llm_bill(due_date=None)))
    assert bill is not None and bill.due_date is None


def test_no_amount_means_nothing_to_log():
    assert extract_bill(make_email(), chain_returning(llm_bill(amount=None))) is None


def test_zero_or_negative_amount_means_nothing_to_log():
    assert extract_bill(make_email(), chain_returning(llm_bill(amount=0))) is None
    assert extract_bill(make_email(), chain_returning(llm_bill(amount=-5))) is None


def test_blank_currency_means_nothing_to_log():
    assert extract_bill(make_email(), chain_returning(llm_bill(currency="  "))) is None


def test_blank_vendor_falls_back_to_the_sender_address():
    bill = extract_bill(make_email(), chain_returning(llm_bill(vendor=" ")))
    assert bill is not None and bill.vendor == "statements@hdfcbank.net"


def test_low_confidence_still_returns_the_bill_with_its_confidence():
    bill = extract_bill(make_email(), chain_returning(llm_bill(confidence=0.4)))
    assert bill is not None and bill.confidence == 0.4


def test_inputs_keep_amounts_but_mask_account_numbers():
    email = make_email(body_preview="A/c 123456789012 debited Rs 125000.00")
    inputs = build_bill_inputs(email)
    assert "Rs 125000.00" in inputs["body_preview"]
    assert "123456789012" not in inputs["body_preview"]
    assert "[NUMBER]" in inputs["body_preview"]


def test_inputs_trim_the_redacted_body_to_the_limit():
    email = make_email(body_preview="word " * 1000)
    assert len(build_bill_inputs(email)["body_preview"]) <= BODY_CHARS


def test_the_chain_receives_the_redacted_inputs():
    chain = chain_returning(llm_bill())
    extract_bill(make_email(subject="Pay 123456789012 now"), chain)
    assert "123456789012" not in chain.seen[0]["subject"]
    assert chain.seen[0]["sender"] == "HDFC Bank <statements@hdfcbank.net>"


def test_extractor_asks_the_model_for_the_llmbill_shape():
    asked = []

    def with_structured_output(schema):
        asked.append(schema)
        return RunnableLambda(lambda _prompt: llm_bill())

    llm = SimpleNamespace(with_structured_output=with_structured_output)
    chain = build_extractor(llm)
    assert asked == [LLMBill]
    assert chain.invoke(build_bill_inputs(make_email())).vendor == "HDFC Bank"
