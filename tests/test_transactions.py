import re
from decimal import Decimal
from types import SimpleNamespace

import httpx
import openai
from langchain_core.runnables import RunnableLambda

from agent.nodes.transactions import (
    BODY_CHARS,
    TRANSACTIONS_PER_REQUEST,
    LLMTransactionBatch,
    LLMTransactionItem,
    build_transaction_extractor,
    extract_transactions,
)
from agent.schemas import Email


def make_email(
    mid="m1", subject="You have done a UPI txn", body="Rs. 50.00 spent"
) -> Email:
    return Email(
        id=mid,
        thread_id=f"t-{mid}",
        sender="Example Bank <alerts@examplebank.bank.in>",
        subject=subject,
        body_preview=body,
    )


def item(index, amount=50.0, currency="INR", payee=None, via="UPI", direction="debit"):
    return LLMTransactionItem(
        index=index,
        amount=amount,
        currency=currency,
        payee=payee,
        via=via,
        direction=direction,
    )


def chain_returning(*items):
    seen: list[str] = []

    def reply(request):
        seen.append(request["emails"])
        return LLMTransactionBatch(items=list(items))

    chain = RunnableLambda(reply)
    chain.seen = seen  # type: ignore[attr-defined]
    return chain


def test_an_answer_becomes_a_transaction_keyed_by_email_id():
    chain = chain_returning(item(1, 450.5, "inr", "Cafe Blue", "UPI", "debit"))
    result = extract_transactions([make_email("a")], chain)
    tx = result["a"]
    assert tx.email_id == "a" and tx.amount == Decimal("450.5") and tx.currency == "INR"
    assert tx.payee == "Cafe Blue" and tx.via == "UPI" and tx.direction == "debit"


def test_an_alert_without_a_usable_amount_or_currency_gets_no_row():
    emails = [make_email("none"), make_email("zero"), make_email("nocur")]
    chain = chain_returning(
        item(1, amount=None), item(2, amount=0), item(3, currency="  ")
    )
    assert extract_transactions(emails, chain) == {}


def test_how_it_was_paid_is_normalised_to_a_small_known_set():
    emails = [make_email(str(i)) for i in range(4)]
    chain = chain_returning(
        item(1, via="upi"),
        item(2, via="Credit Card"),
        item(3, via="DEBIT CARD"),
        item(4, via="wallet"),
    )
    result = extract_transactions(emails, chain)
    assert [result[str(i)].via for i in range(4)] == [
        "UPI",
        "credit card",
        "debit card",
        "other",
    ]


def test_the_payee_is_optional_and_cleaned_of_links_and_length():
    emails = [make_email("a"), make_email("b"), make_email("c")]
    chain = chain_returning(
        item(1, payee=None),
        item(2, payee="  "),
        item(3, payee="Shop https://evil.example/x " + "x" * 200),
    )
    result = extract_transactions(emails, chain)
    assert result["a"].payee is None and result["b"].payee is None
    assert "evil" not in result["c"].payee and len(result["c"].payee) <= 60


def test_money_in_is_marked_as_a_credit():
    result = extract_transactions(
        [make_email("a")], chain_returning(item(1, direction="credit"))
    )
    assert result["a"].direction == "credit"


def test_ten_alerts_go_in_one_request_and_longer_lists_are_split():
    assert TRANSACTIONS_PER_REQUEST == 10
    sizes = []

    def reply(request):
        n = request["emails"].count("<email id=")
        sizes.append(n)
        return LLMTransactionBatch(items=[item(i) for i in range(1, n + 1)])

    emails = [make_email(str(i)) for i in range(25)]
    result = extract_transactions(emails, RunnableLambda(reply))
    assert sorted(sizes) == [5, 10, 10] and len(result) == 25


def test_skipped_duplicate_and_unknown_answers_are_handled_by_id():
    emails = [make_email("a"), make_email("b")]
    chain = chain_returning(item(1, 10.0), item(1, 99.0), item(9, 5.0), item(0, 5.0))
    result = extract_transactions(emails, chain)
    assert list(result) == ["a"] and result["a"].amount == Decimal(
        "10.0"
    )  # first wins; b skipped


def test_a_content_filter_rejection_drops_only_that_alert():
    def filtered(request):
        if "BADTEXT" in request["emails"]:
            response = httpx.Response(
                400, request=httpx.Request("POST", "https://example.invalid/")
            )
            raise openai.BadRequestError(
                "rejected", response=response, body={"code": "content_filter"}
            )
        n = request["emails"].count("<email id=")
        return LLMTransactionBatch(items=[item(i) for i in range(1, n + 1)])

    emails = [make_email("ok"), make_email("bad", body="BADTEXT")]
    assert list(extract_transactions(emails, RunnableLambda(filtered))) == ["ok"]


def test_the_model_sees_redacted_text_with_the_amount_intact():
    chain = chain_returning(item(1))
    email = make_email(
        body="A/c 123456789012 debited Rs. 125000.00 see https://bank.com/x?t=1"
    )
    extract_transactions([email], chain)
    text = chain.seen[0]
    assert (
        "Rs. 125000.00" in text
        and "123456789012" not in text
        and "[LINK:bank.com]" in text
    )


def test_the_body_is_kept_short():
    chain = chain_returning(item(1))
    extract_transactions([make_email(body="x" * 3000)], chain)
    assert (
        BODY_CHARS == 600
        and "x" * 600 in chain.seen[0]
        and "x" * 601 not in chain.seen[0]
    )


def test_no_alerts_means_no_model_call():
    class Exploding:
        def batch(self, *_a, **_k):
            raise AssertionError("must not be called")

    assert extract_transactions([], Exploding()) == {}


def test_the_built_chain_asks_for_the_batch_shape_with_safety_text():
    captured = {}

    def fake_structured(prompt_value):
        captured["text"] = prompt_value.to_string()
        return LLMTransactionBatch(items=[item(1)])

    def with_structured_output(schema):
        captured["schema"] = schema
        return RunnableLambda(fake_structured)

    chain = build_transaction_extractor(
        SimpleNamespace(with_structured_output=with_structured_output)
    )
    extract_transactions([make_email()], chain)
    assert captured["schema"] is LLMTransactionBatch
    text = captured["text"].lower()
    assert "untrusted" in text and "never write" in text and "link" in text
    assert (
        "upi" in text and "credit" in text and "rs" in text
    )  # the rupee marker means INR
    assert re.search(r"payee", text)
