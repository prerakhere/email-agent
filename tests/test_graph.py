from langchain_core.runnables import RunnableLambda

from agent.graph import build_graph, collect_bill_items
from agent.nodes.classify import LLMClassification
from agent.nodes.extract import LLMBill
from agent.schemas import Category, Email


def make_email(mid: str, sender: str, subject: str = "s") -> Email:
    return Email(id=mid, thread_id=f"t-{mid}", sender=sender, subject=subject)


class FakeGmail:
    def __init__(self, emails, labels=(), label_ids=None):
        self._emails = emails
        self._labels = list(labels)
        self._label_ids = label_ids or {}
        self.fetch_args = None

    def fetch_recent(self, days, max_results=100):
        self.fetch_args = (days, max_results)
        return self._emails

    def list_label_names(self):
        return self._labels

    def label_ids_by_name(self):
        return self._label_ids


class FakeChain:
    """Stands in for prompt|llm. Records which emails reached the LLM."""

    def __init__(self, category=Category.PROMOTIONS, confidence=0.9):
        self.seen_subjects: list[str] = []
        self._answer = LLMClassification(
            category=category, confidence=confidence, reason="llm said so"
        )
        self.runnable = RunnableLambda(self._invoke)

    def _invoke(self, inputs):
        self.seen_subjects.append(inputs["subject"])
        return self._answer


RULES = {"bytebytego.com": Category.NEWSLETTERS}


def run(emails, chain, rules=RULES, labels=(), label_ids=None, **kwargs):
    gmail = FakeGmail(emails, labels, label_ids)
    graph = build_graph(gmail, rules, chain.runnable, **kwargs)
    return graph.invoke({}), gmail


def test_rule_matched_mail_never_reaches_the_llm():
    chain = FakeChain()
    state, _ = run([make_email("1", "a@bytebytego.com", "weekly")], chain)
    assert chain.seen_subjects == []
    (proposal,) = state["proposals"]
    assert proposal.category == Category.NEWSLETTERS
    assert proposal.source == "rule"


def test_unmatched_mail_goes_to_the_llm():
    chain = FakeChain(Category.PROMOTIONS, 0.9)
    state, _ = run([make_email("1", "deals@shop.com", "sale")], chain)
    assert chain.seen_subjects == ["sale"]
    (proposal,) = state["proposals"]
    assert proposal.category == Category.PROMOTIONS
    assert proposal.source == "llm"
    assert proposal.reason == "llm said so"


def test_llm_only_sees_the_unmatched_emails_and_order_is_preserved():
    chain = FakeChain()
    emails = [
        make_email("1", "deals@shop.com", "first"),
        make_email("2", "a@bytebytego.com", "second"),
        make_email("3", "x@other.com", "third"),
    ]
    state, _ = run(emails, chain)
    assert chain.seen_subjects == ["first", "third"]
    assert [p.email_id for p in state["proposals"]] == ["1", "2", "3"]


def test_low_confidence_llm_answer_is_proposed_as_needs_review():
    chain = FakeChain(Category.BILLS, 0.4)
    state, _ = run([make_email("1", "x@other.com")], chain)
    (proposal,) = state["proposals"]
    assert proposal.category == Category.NEEDS_REVIEW
    assert proposal.label == "Agent/Needs-Review"


def test_label_uses_existing_gmail_label_when_present_else_agent_fallback():
    chain = FakeChain()
    with_label, _ = run(
        [make_email("1", "a@bytebytego.com")], chain, labels=["Newsletters"]
    )
    without_label, _ = run([make_email("1", "a@bytebytego.com")], chain, labels=[])
    assert with_label["proposals"][0].label == "Newsletters"
    assert without_label["proposals"][0].label == "Agent/Newsletters"


def test_proposal_carries_sender_subject_and_confidence_for_the_table():
    chain = FakeChain(Category.PROMOTIONS, 0.85)
    state, _ = run([make_email("9", "Shop <deals@shop.com>", "50% off")], chain)
    (proposal,) = state["proposals"]
    assert proposal.email_id == "9"
    assert proposal.sender == "Shop <deals@shop.com>"
    assert proposal.subject == "50% off"
    assert proposal.confidence == 0.85


def test_fetch_uses_configured_window_and_cap():
    chain = FakeChain()
    _, gmail = run([], chain, days=7, max_results=25)
    assert gmail.fetch_args == (7, 25)


def test_empty_inbox_gives_no_proposals_and_no_llm_calls():
    chain = FakeChain()
    state, _ = run([], chain)
    assert state["proposals"] == []
    assert chain.seen_subjects == []


def test_starred_flag_is_carried_into_the_proposal():
    starred = Email(
        id="1", thread_id="t1", sender="a@x.com", subject="s", label_ids=["STARRED"]
    )
    plain = make_email("2", "b@x.com")
    state, _ = run([starred, plain], FakeChain())
    assert [p.starred for p in state["proposals"]] == [True, False]


def test_mail_that_already_has_a_user_label_is_skipped_entirely():
    done = Email(
        id="1",
        thread_id="t1",
        sender="a@x.com",
        subject="old",
        label_ids=["INBOX", "Label_7"],
    )
    fresh = Email(
        id="2",
        thread_id="t2",
        sender="b@x.com",
        subject="new",
        label_ids=["INBOX", "UNREAD"],
    )
    chain = FakeChain()
    state, _ = run([done, fresh], chain, label_ids={"Agent/Job-Alerts": "Label_7"})
    assert chain.seen_subjects == ["new"]
    assert [p.email_id for p in state["proposals"]] == ["2"]


def test_mail_with_only_system_labels_is_still_processed():
    email = Email(
        id="1",
        thread_id="t1",
        sender="a@x.com",
        subject="s",
        label_ids=["INBOX", "UNREAD", "CATEGORY_PROMOTIONS"],
    )
    state, _ = run([email], FakeChain(), label_ids={"Newsletters": "Label_1"})
    assert len(state["proposals"]) == 1


class FakeExtractor:
    """Stands in for the extraction chain. Records which emails reached it."""

    def __init__(self, amount=1250.0):
        self.seen_subjects: list[str] = []
        self._answer = LLMBill(
            vendor="HDFC Bank", amount=amount, currency="INR", confidence=0.9
        )
        self.runnable = RunnableLambda(self._invoke)

    def _invoke(self, inputs):
        self.seen_subjects.append(inputs["subject"])
        return self._answer


BANK_RULES = {"stmt@bank.com": Category.BILLS, "shop@store.com": Category.RECEIPTS}


def test_bill_mail_is_extracted_into_state_bills():
    extractor = FakeExtractor()
    state, _ = run(
        [make_email("1", "stmt@bank.com", "Statement")],
        FakeChain(),
        rules=BANK_RULES,
        extractor=extractor.runnable,
    )
    assert extractor.seen_subjects == ["Statement"]
    assert state["bills"]["1"].vendor == "HDFC Bank"
    assert str(state["bills"]["1"].amount) == "1250.0"


def test_receipts_are_extracted_too():
    extractor = FakeExtractor()
    state, _ = run(
        [make_email("1", "shop@store.com", "Your order")],
        FakeChain(),
        rules=BANK_RULES,
        extractor=extractor.runnable,
    )
    assert "1" in state["bills"]


def test_other_categories_never_reach_the_extractor():
    extractor = FakeExtractor()
    state, _ = run(
        [make_email("1", "deals@shop.com", "sale")],
        FakeChain(Category.PROMOTIONS, 0.9),
        extractor=extractor.runnable,
    )
    assert extractor.seen_subjects == []
    assert state.get("bills", {}) == {}


def test_low_confidence_bill_is_needs_review_and_not_extracted():
    extractor = FakeExtractor()
    state, _ = run(
        [make_email("1", "x@other.com", "maybe a bill")],
        FakeChain(Category.BILLS, 0.4),
        extractor=extractor.runnable,
    )
    assert extractor.seen_subjects == []
    assert state.get("bills", {}) == {}


def test_a_bill_mail_with_no_usable_amount_is_left_out_of_bills():
    extractor = FakeExtractor(amount=None)
    state, _ = run(
        [make_email("1", "stmt@bank.com", "Reminder")],
        FakeChain(),
        rules=BANK_RULES,
        extractor=extractor.runnable,
    )
    assert extractor.seen_subjects == ["Reminder"]
    assert state["bills"] == {}


def test_without_an_extractor_the_graph_behaves_as_before():
    state, _ = run(
        [make_email("1", "stmt@bank.com", "Statement")], FakeChain(), rules=BANK_RULES
    )
    assert state["proposals"][0].category == Category.BILLS
    assert "bills" not in state


def test_collect_bill_items_pairs_email_category_and_bill_in_email_order():
    extractor = FakeExtractor()
    emails = [
        make_email("1", "deals@shop.com", "sale"),
        make_email("2", "shop@store.com", "Your order"),
        make_email("3", "stmt@bank.com", "Statement"),
    ]
    state, _ = run(
        emails,
        FakeChain(Category.PROMOTIONS, 0.9),
        rules=BANK_RULES,
        extractor=extractor.runnable,
    )
    items = collect_bill_items(state)
    assert [(e.id, c) for e, c, _ in items] == [
        ("2", Category.RECEIPTS),
        ("3", Category.BILLS),
    ]
    assert all(bill.currency == "INR" for _, _, bill in items)
