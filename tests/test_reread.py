"""Re-read when unsure: emails the first pass left in Needs-Review are classified once more with a
much longer body. The graph loops classify -> reread -> classify, at most `max_rereads` times."""

import re

import httpx
import openai
from langchain_core.runnables import RunnableLambda

from agent.graph import build_graph
from agent.nodes.classify import BODY_CHARS, REREAD_BODY_CHARS, LLMBatch, LLMItem
from agent.profile import Profile
from agent.schemas import Category, Email

LONG_BODY = "lorem ipsum " * 400  # 4800 chars: more than either pass sends


def email(mid: str, subject: str) -> Email:
    return Email(
        id=mid,
        thread_id=f"t-{mid}",
        sender=f"someone{mid}@example.com",
        subject=subject,
        body_preview=LONG_BODY,
    )


def content_filter_error():
    response = httpx.Response(
        400, request=httpx.Request("POST", "https://example.invalid/")
    )
    return openai.BadRequestError(
        "rejected",
        response=response,
        body={"code": "content_filter", "message": "rejected"},
    )


class ScriptedChain:
    """A fake model whose answer for each email depends on its subject and on whether it was given
    the long body. `answer(subject, long)` returns (category, confidence), or None to skip the
    email. Every request is recorded as a list of (subject, body length) pairs."""

    def __init__(self, answer, blocked_subjects=()):
        self.calls: list[list[tuple[str, int]]] = []
        self._answer = answer
        self._blocked = set(blocked_subjects)
        self.runnable = RunnableLambda(self._invoke)

    def _invoke(self, inputs):
        blocks = re.findall(
            r"Subject: (.*?)\n.*?Body start:\n(.*?)\n</email>",
            inputs["emails"],
            re.DOTALL,
        )
        seen = [(subject, len(body)) for subject, body in blocks]
        self.calls.append(seen)
        if any(subject in self._blocked for subject, _ in seen):
            raise content_filter_error()
        items = []
        for n, (subject, length) in enumerate(seen, start=1):
            answer = self._answer(subject, length > BODY_CHARS)
            if answer is not None:
                category, confidence = answer
                items.append(
                    LLMItem(
                        index=n,
                        category=category,
                        confidence=confidence,
                        reason="because",
                    )
                )
        return LLMBatch(items=items)

    def subjects_per_call(self) -> list[list[str]]:
        return [[subject for subject, _ in call] for call in self.calls]


def run(emails, chain, **kwargs):
    class Gmail:
        def fetch_recent(self, days, max_results=100):
            return emails

        def list_label_names(self):
            return []

        def label_ids_by_name(self):
            return {}

    kwargs.setdefault("profile", Profile())
    return build_graph(Gmail(), {}, chain.runnable, **kwargs).invoke({})


def clearer_with_more_text(subject, long):
    return (Category.BILLS, 0.9) if long else (Category.BILLS, 0.4)


def test_an_unsure_email_is_read_again_with_the_longer_body():
    chain = ScriptedChain(clearer_with_more_text)
    run([email("1", "card statement")], chain)
    assert len(chain.calls) == 2
    ((_, first_length),) = chain.calls[0]
    ((_, second_length),) = chain.calls[1]
    assert first_length == BODY_CHARS
    assert second_length == REREAD_BODY_CHARS


def test_the_second_answer_replaces_the_first_and_says_it_came_from_a_reread():
    chain = ScriptedChain(clearer_with_more_text)
    state = run([email("1", "card statement")], chain)
    result = state["classifications"]["1"]
    assert result.category == Category.BILLS
    assert result.confidence == 0.9
    assert "after re-reading the full email" in result.reason
    assert state["proposals"][0].category == Category.BILLS


def test_confident_emails_are_not_sent_again():
    def answer(subject, long):
        return (
            (Category.PROMOTIONS, 0.95)
            if subject == "sale"
            else clearer_with_more_text(subject, long)
        )

    chain = ScriptedChain(answer)
    state = run([email("1", "sale"), email("2", "card statement")], chain)
    assert chain.subjects_per_call() == [["sale", "card statement"], ["card statement"]]
    assert "re-reading" not in state["classifications"]["1"].reason


def test_an_email_still_unsure_after_the_reread_stays_needs_review_and_the_loop_stops():
    chain = ScriptedChain(lambda subject, long: (Category.BILLS, 0.4))
    state = run([email("1", "mystery")], chain)
    assert len(chain.calls) == 2  # first pass + one re-read, never more
    assert state["classifications"]["1"].category == Category.NEEDS_REVIEW
    assert state["proposals"][0].label == "Agent/Needs-Review"


def test_nothing_unsure_means_no_extra_model_call():
    chain = ScriptedChain(lambda subject, long: (Category.PROMOTIONS, 0.9))
    run([email("1", "sale"), email("2", "offer")], chain)
    assert len(chain.calls) == 1


def test_an_email_the_model_itself_put_in_needs_review_gets_a_second_look():
    def answer(subject, long):
        return (Category.NEWSLETTERS, 0.9) if long else (Category.NEEDS_REVIEW, 0.9)

    chain = ScriptedChain(answer)
    state = run([email("1", "weekly notes")], chain)
    assert state["classifications"]["1"].category == Category.NEWSLETTERS


def test_an_email_the_model_skipped_gets_a_second_look():
    chain = ScriptedChain(
        lambda subject, long: (Category.RECEIPTS, 0.9) if long else None
    )
    state = run([email("1", "your order")], chain)
    assert state["classifications"]["1"].category == Category.RECEIPTS


def test_an_email_blocked_by_the_content_filter_is_not_read_again():
    chain = ScriptedChain(
        lambda subject, long: (Category.PROMOTIONS, 0.9), blocked_subjects={"blocked"}
    )
    state = run([email("1", "blocked")], chain)
    assert all(length == BODY_CHARS for call in chain.calls for _, length in call)
    assert state["classifications"]["1"].category == Category.NEEDS_REVIEW


def test_rereading_can_be_switched_off():
    chain = ScriptedChain(clearer_with_more_text)
    state = run([email("1", "card statement")], chain, max_rereads=0)
    assert len(chain.calls) == 1
    assert state["classifications"]["1"].category == Category.NEEDS_REVIEW


def test_mail_decided_by_a_rule_is_never_reread():
    chain = ScriptedChain(clearer_with_more_text)

    class Gmail:
        def fetch_recent(self, days, max_results=100):
            return [email("1", "weekly")]

        def list_label_names(self):
            return []

        def label_ids_by_name(self):
            return {}

    rules = {"someone1@example.com": Category.NEWSLETTERS}
    state = build_graph(Gmail(), rules, chain.runnable, profile=Profile()).invoke({})
    assert chain.calls == []
    assert state["classifications"]["1"].source == "rule"
