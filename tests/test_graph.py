import re
from datetime import UTC, datetime

from langchain_core.runnables import RunnableLambda

from agent.graph import build_graph, collect_bill_items, collect_transactions
from agent.nodes.classify import DEFAULT_CONCURRENCY, LLMBatch, LLMItem
from agent.nodes.extract import LLMBill
from agent.nodes.transactions import LLMTransactionBatch, LLMTransactionItem
from agent.profile import Profile
from agent.schemas import Category, Email


def make_email(mid: str, sender: str, subject: str = "s") -> Email:
    return Email(id=mid, thread_id=f"t-{mid}", sender=sender, subject=subject)


class FakeGmail:
    def __init__(self, emails, labels=(), label_ids=None):
        self._emails = emails
        self._labels = list(labels)
        self._label_ids = label_ids or {}
        self.fetch_args = None
        self.since_args = None

    def fetch_recent(self, days, max_results=100):
        self.fetch_args = (days, max_results)
        return self._emails

    def fetch_since(self, since, max_results=500):
        self.since_args = (since, max_results)
        return self._emails

    def list_label_names(self):
        return self._labels

    def label_ids_by_name(self):
        return self._label_ids


class FakeChain:
    """Stands in for prompt|llm. Answers every email it is sent and records their subjects."""

    def __init__(self, category=Category.PROMOTIONS, confidence=0.9):
        self.seen_subjects: list[str] = []
        self._category = category
        self._confidence = confidence
        self.runnable = RunnableLambda(self._invoke)

    def _invoke(self, inputs):
        subjects = re.findall(r"^Subject: (.*)$", inputs["emails"], re.MULTILINE)
        self.seen_subjects.extend(subjects)
        return LLMBatch(
            items=[
                LLMItem(
                    index=n,
                    category=self._category,
                    confidence=self._confidence,
                    reason="llm said so",
                )
                for n in range(1, len(subjects) + 1)
            ]
        )


RULES = {"weeklytech.example": Category.NEWSLETTERS}


# A person's taste: folders that teach a category and existing labels to file into.
PROFILE = Profile(
    learn_from_folders={
        "Newsletters": Category.NEWSLETTERS,
        "Read Later": Category.NEWSLETTERS,
        "Money/Statements, Receipts": Category.BILLS,
    },
    file_into={
        Category.BILLS: ["Money/Statements, Receipts"],
        Category.NEWSLETTERS: ["Newsletters"],
    },
)


def run(emails, chain, rules=RULES, labels=(), label_ids=None, **kwargs):
    gmail = FakeGmail(emails, labels, label_ids)
    kwargs.setdefault("profile", PROFILE)
    graph = build_graph(gmail, rules, chain.runnable, **kwargs)
    return graph.invoke({}), gmail


def test_rule_matched_mail_never_reaches_the_llm():
    chain = FakeChain()
    state, _ = run([make_email("1", "a@weeklytech.example", "weekly")], chain)
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
        make_email("2", "a@weeklytech.example", "second"),
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
        [make_email("1", "a@weeklytech.example")], chain, labels=["Newsletters"]
    )
    without_label, _ = run([make_email("1", "a@weeklytech.example")], chain, labels=[])
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
            vendor="Example Bank", amount=amount, currency="INR", confidence=0.9
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
    assert state["bills"]["1"].vendor == "Example Bank"
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


class BatchRecorder:
    """A chain that only understands batch(): records every request's subjects and the config."""

    def __init__(self):
        self.requests: list[list[str]] = []
        self.config = None

    def batch(self, inputs, config=None, **_kwargs):
        self.config = config
        replies = []
        for request in inputs:
            subjects = re.findall(r"^Subject: (.*)$", request["emails"], re.MULTILINE)
            self.requests.append(subjects)
            replies.append(
                LLMBatch(
                    items=[
                        LLMItem(
                            index=n,
                            category=Category.PROMOTIONS,
                            confidence=0.9,
                            reason="batched",
                        )
                        for n in range(1, len(subjects) + 1)
                    ]
                )
            )
        return replies


def run_with_recorder(emails, recorder, **kwargs):
    graph = build_graph(FakeGmail(emails), RULES, recorder, **kwargs)
    return graph.invoke({})


def test_all_unmatched_mail_goes_to_the_model_together_in_order():
    recorder = BatchRecorder()
    emails = [
        make_email("1", "deals@shop.com", "first"),
        make_email("2", "a@weeklytech.example", "second"),  # decided by a rule
        make_email("3", "x@other.com", "third"),
    ]
    state = run_with_recorder(emails, recorder)
    assert recorder.requests == [
        ["first", "third"]
    ]  # one request, rule-matched mail left out
    assert [p.email_id for p in state["proposals"]] == ["1", "2", "3"]
    assert state["proposals"][0].reason == "batched"


def test_the_concurrency_cap_is_configurable_and_has_a_default():
    recorder = BatchRecorder()
    run_with_recorder([make_email("1", "x@other.com")], recorder)
    assert recorder.config == {"max_concurrency": DEFAULT_CONCURRENCY}
    recorder = BatchRecorder()
    run_with_recorder([make_email("1", "x@other.com")], recorder, max_concurrency=3)
    assert recorder.config == {"max_concurrency": 3}


def test_the_batch_size_can_be_set_from_the_graph():
    recorder = BatchRecorder()
    emails = [make_email(str(i), f"x{i}@other.com", f"s{i}") for i in range(5)]
    run_with_recorder(emails, recorder, batch_size=2)
    assert sorted(len(r) for r in recorder.requests) == [1, 2, 2]


def test_no_model_call_at_all_when_every_mail_is_decided_by_a_rule():
    recorder = BatchRecorder()
    run_with_recorder([make_email("1", "a@weeklytech.example")], recorder)
    assert recorder.requests == []


# ---- digest window mode: everything since a moment, labelled or not ----

SINCE = datetime(2026, 11, 7, 2, 30, tzinfo=UTC)
LABEL_IDS = {
    "Agent/Job-Alerts": "L_jobs",
    "Agent/Promotions": "L_promo",
    "Travel Plans": "L_apps",
}


def labelled(mid, label_id, sender="x@other.com", subject="s"):
    return Email(
        id=mid,
        thread_id=f"t-{mid}",
        sender=sender,
        subject=subject,
        label_ids=["INBOX", label_id],
    )


def run_window(emails, chain, **kwargs):
    return run(emails, chain, label_ids=LABEL_IDS, since=SINCE, **kwargs)


def test_window_mode_fetches_since_the_moment_not_by_days():
    chain = FakeChain()
    _, gmail = run_window([make_email("1", "a@x.com")], chain, max_results=250)
    assert gmail.since_args == (SINCE, 250)
    assert gmail.fetch_args is None


def test_window_mode_keeps_mail_that_already_has_a_label():
    chain = FakeChain()
    emails = [labelled("1", "L_jobs"), make_email("2", "b@x.com")]
    state, _ = run_window(emails, chain)
    assert [e.id for e in state["emails"]] == ["1", "2"]
    assert state["filed_ids"] == ["1"]


def test_labelled_mail_takes_its_category_from_the_label_with_no_model_call():
    chain = FakeChain()
    state, _ = run_window([labelled("1", "L_jobs", subject="a job")], chain)
    assert chain.seen_subjects == []
    found = state["classifications"]["1"]
    assert found.category == Category.JOB_ALERTS
    assert found.source == "label" and found.confidence == 1.0


def test_a_label_beats_a_sender_rule():
    chain = FakeChain()
    mail = labelled(
        "1", "L_promo", sender="a@weeklytech.example"
    )  # rule says newsletters
    state, _ = run_window([mail], chain)
    assert state["classifications"]["1"].category == Category.PROMOTIONS


def test_labelled_mail_whose_label_says_nothing_is_still_classified_by_the_model():
    chain = FakeChain(Category.IMPORTANT, 0.9)
    state, _ = run_window([labelled("1", "L_apps", subject="my application")], chain)
    assert chain.seen_subjects == ["my application"]
    assert state["classifications"]["1"].category == Category.IMPORTANT
    assert state["classifications"]["1"].source == "llm"


def test_only_mail_without_a_label_gets_a_label_proposal():
    chain = FakeChain()
    emails = [
        labelled("1", "L_jobs"),
        labelled("2", "L_apps"),
        make_email("3", "c@x.com"),
    ]
    state, _ = run_window(emails, chain)
    assert [p.email_id for p in state["proposals"]] == ["3"]


def test_window_mode_still_extracts_bills_from_labelled_mail():
    extractor = FakeExtractor()
    bill_labels = {"Money/Statements, Receipts": "L_fin"}
    graph = build_graph(
        FakeGmail(
            [labelled("1", "L_fin", subject="Statement")],
            label_ids=bill_labels,
        ),
        {},
        FakeChain().runnable,
        since=SINCE,
        extractor=extractor.runnable,
        profile=PROFILE,
    )
    state = graph.invoke({})
    assert state["classifications"]["1"].category == Category.BILLS
    assert "1" in state["bills"]


def test_day_mode_is_unchanged_and_still_drops_labelled_mail():
    chain = FakeChain()
    emails = [labelled("1", "L_jobs"), make_email("2", "b@x.com")]
    state, gmail = run(emails, chain, label_ids=LABEL_IDS)
    assert gmail.fetch_args == (3, 100) and gmail.since_args is None
    assert [e.id for e in state["emails"]] == ["2"]
    assert state.get("filed_ids", []) == []


# ---- transaction alerts: extracted like bills, but only for the transactions category ----


class FakeTransactionExtractor:
    """Stands in for the transaction chain. Records which alerts reached it."""

    def __init__(self):
        self.seen_subjects: list[str] = []
        self.runnable = RunnableLambda(self._invoke)

    def _invoke(self, request):
        subjects = re.findall(r"^Subject: (.*)$", request["emails"], re.MULTILINE)
        self.seen_subjects.extend(subjects)
        return LLMTransactionBatch(
            items=[
                LLMTransactionItem(index=n, amount=50.0, currency="INR", via="UPI")
                for n in range(1, len(subjects) + 1)
            ]
        )


TX_RULES = {"alerts@bank.com": Category.TRANSACTIONS, **BANK_RULES}


def test_a_transaction_alert_is_extracted_into_state_transactions():
    tx = FakeTransactionExtractor()
    state, _ = run(
        [make_email("1", "alerts@bank.com", "UPI txn")],
        FakeChain(),
        rules=TX_RULES,
        transaction_extractor=tx.runnable,
    )
    assert tx.seen_subjects == ["UPI txn"]
    assert str(state["transactions"]["1"].amount) == "50.0"
    assert state["transactions"]["1"].via == "UPI"


def test_other_mail_never_reaches_the_transaction_extractor():
    tx = FakeTransactionExtractor()
    state, _ = run(
        [
            make_email("1", "deals@shop.com", "sale"),
            make_email("2", "stmt@bank.com", "Statement"),
        ],
        FakeChain(Category.PROMOTIONS, 0.9),
        rules=TX_RULES,
        transaction_extractor=tx.runnable,
    )
    assert tx.seen_subjects == [] and state.get("transactions", {}) == {}


def test_without_a_transaction_extractor_nothing_is_extracted_for_alerts():
    state, _ = run(
        [make_email("1", "alerts@bank.com", "UPI txn")], FakeChain(), rules=TX_RULES
    )
    assert "transactions" not in state
    assert state["proposals"][0].category == Category.TRANSACTIONS


def test_bills_and_transactions_are_extracted_in_the_same_run_each_from_its_own_mail():
    bills, tx = FakeExtractor(), FakeTransactionExtractor()
    emails = [
        make_email("1", "stmt@bank.com", "Statement"),
        make_email("2", "alerts@bank.com", "UPI txn"),
    ]
    state, _ = run(
        emails,
        FakeChain(),
        rules=TX_RULES,
        extractor=bills.runnable,
        transaction_extractor=tx.runnable,
    )
    assert bills.seen_subjects == ["Statement"] and tx.seen_subjects == ["UPI txn"]
    assert list(state["bills"]) == ["1"] and list(state["transactions"]) == ["2"]


def test_a_low_confidence_transaction_is_needs_review_and_not_extracted():
    tx = FakeTransactionExtractor()
    state, _ = run(
        [make_email("1", "x@other.com", "maybe a payment")],
        FakeChain(Category.TRANSACTIONS, 0.4),
        transaction_extractor=tx.runnable,
    )
    assert tx.seen_subjects == [] and state.get("transactions", {}) == {}


def test_collect_transactions_pairs_each_email_with_its_transaction_in_email_order():
    tx = FakeTransactionExtractor()
    emails = [
        make_email("1", "deals@shop.com", "sale"),
        make_email("2", "alerts@bank.com", "first"),
        make_email("3", "alerts@bank.com", "second"),
    ]
    state, _ = run(
        emails,
        FakeChain(Category.PROMOTIONS, 0.9),
        rules=TX_RULES,
        transaction_extractor=tx.runnable,
    )
    assert [(e.id, t.email_id) for e, t in collect_transactions(state)] == [
        ("2", "2"),
        ("3", "3"),
    ]


def test_the_agents_own_labels_can_be_rechecked_while_the_users_folders_stay_trusted():
    chain = FakeChain(Category.TRANSACTIONS, 0.9)
    emails = [
        labelled("1", "L_jobs", subject="alert the agent labelled earlier"),
        labelled("2", "L_news", subject="filed by the user"),
    ]
    ids = {**LABEL_IDS, "Newsletters": "L_news"}
    state, _ = run(emails, chain, label_ids=ids, since=SINCE, trust_agent_labels=False)
    assert chain.seen_subjects == ["alert the agent labelled earlier"]  # re-classified
    assert state["classifications"]["1"].category == Category.TRANSACTIONS
    assert (
        state["classifications"]["2"].category == Category.NEWSLETTERS
    )  # the user's folder wins
    assert state["proposals"] == []  # filed mail never gets a second label


def test_with_no_profile_labels_are_agent_labels_and_user_folders_teach_nothing():
    chain = FakeChain(Category.NEWSLETTERS, 0.9)
    state, _ = run(
        [make_email("1", "deals@shop.com", "hello")],
        chain,
        labels=["Newsletters"],
        profile=Profile(),
    )
    assert state["proposals"][0].label == "Agent/Newsletters"
