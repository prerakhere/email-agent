"""The LangGraph pipeline: fetch -> prefilter -> classify -> propose, then (only if there are
bills/receipts and an extractor was given) extract. The graph never writes anywhere: acting on
its output (labelling, logging to the sheet) is a separate, lock-guarded step.

State is one shared typed dict. Each node is a plain function that returns only the keys it
changed; LangGraph merges those into the state. Dependencies (Gmail client, rules, LLM chain)
are injected so tests use fakes.
"""

from datetime import datetime
from typing import TypedDict

from langchain_core.runnables import Runnable
from langgraph.graph import END, START, StateGraph

from agent.labels import category_for_labels, resolve_label
from agent.nodes.classify import BATCH_SIZE, DEFAULT_CONCURRENCY, classify_many
from agent.nodes.extract import extract_bill
from agent.nodes.prefilter import prefilter
from agent.schemas import Bill, Category, Classification, Email, Proposal

BILLING = {Category.BILLS, Category.RECEIPTS}


class AgentState(TypedDict, total=False):
    emails: list[Email]
    existing_labels: list[str]
    classifications: dict[str, Classification]  # keyed by email id
    proposals: list[Proposal]
    filed_ids: list[str]  # window mode: mail that already carried a user label
    label_names_by_id: dict[str, str]
    # keyed by email id; only bills/receipts with a usable amount
    bills: dict[str, Bill]


def build_graph(
    gmail,
    rules: dict[str, Category],
    chain: Runnable,
    days: int = 3,
    max_results: int = 100,
    extractor: Runnable | None = None,
    max_concurrency: int = DEFAULT_CONCURRENCY,
    batch_size: int = BATCH_SIZE,
    since: datetime | None = None,
):
    def fetch_node(state: AgentState) -> dict:
        ids_by_name = gmail.label_ids_by_name()
        user_label_ids = set(ids_by_name.values())
        if since is not None:
            # Digest window: keep EVERYTHING since the moment, labelled or not. Mail that already
            # carries a user label is "filed": it is summarised but never labelled again.
            emails = gmail.fetch_since(since, max_results=max_results)
            filed = [e.id for e in emails if user_label_ids & set(e.label_ids)]
        else:
            # Day mode: mail that already carries a user label (ours or the user's own) is
            # skipped so it is not re-classified on every run while it stays in the inbox.
            fetched = gmail.fetch_recent(days=days, max_results=max_results)
            emails = [e for e in fetched if not user_label_ids & set(e.label_ids)]
            filed = []
        return {
            "emails": emails,
            "filed_ids": filed,
            "label_names_by_id": {
                label_id: name for name, label_id in ids_by_name.items()
            },
            "existing_labels": gmail.list_label_names(),
        }

    def prefilter_node(state: AgentState) -> dict:
        # Free decisions, no model call: first what a label already says, then sender rules.
        decided = {}
        filed = set(state["filed_ids"])
        for email in state["emails"]:
            if email.id in filed:
                names = [
                    state["label_names_by_id"][label_id]
                    for label_id in email.label_ids
                    if label_id in state["label_names_by_id"]
                ]
                category = category_for_labels(names)
                if category is not None:
                    decided[email.id] = Classification(
                        category=category,
                        confidence=1.0,
                        reason="already carries a label that says so",
                        source="label",
                    )
                    continue
            result = prefilter(email, rules)
            if result is not None:
                decided[email.id] = result
        return {"classifications": decided}

    def classify_node(state: AgentState) -> dict:
        # Only mail no rule decided goes to the model, several emails per request (a 100+ mail day
        # would otherwise hit the request-rate limit). A returned key REPLACES the old value, so we return the
        # merged dict.
        classifications = dict(state["classifications"])
        pending = [e for e in state["emails"] if e.id not in classifications]
        results = classify_many(
            pending, chain, batch_size=batch_size, max_concurrency=max_concurrency
        )
        for email, result in zip(pending, results, strict=True):
            classifications[email.id] = result
        return {"classifications": classifications}

    def propose_node(state: AgentState) -> dict:
        proposals = []
        filed = set(state["filed_ids"])
        for email in state["emails"]:
            if (
                email.id in filed
            ):  # already labelled: summarised later, never labelled again
                continue
            c = state["classifications"][email.id]
            proposals.append(
                Proposal(
                    email_id=email.id,
                    sender=email.sender,
                    subject=email.subject,
                    category=c.category,
                    label=resolve_label(c.category, state["existing_labels"]),
                    confidence=c.confidence,
                    reason=c.reason,
                    source=c.source,
                    starred=email.is_starred,
                )
            )
        return {"proposals": proposals}

    def extract_node(state: AgentState) -> dict:
        bills = {}
        for email in state["emails"]:
            if state["classifications"][email.id].category in BILLING:
                bill = extract_bill(email, extractor)
                if bill is not None:  # None = no usable amount: nothing safe to log
                    bills[email.id] = bill
        return {"bills": bills}

    def route_after_propose(state: AgentState) -> str:
        """Conditional edge: the returned string names the next node."""
        has_billing_mail = any(
            state["classifications"][e.id].category in BILLING for e in state["emails"]
        )
        return "extract" if extractor is not None and has_billing_mail else END

    graph = StateGraph(AgentState)
    graph.add_node("fetch", fetch_node)
    graph.add_node("prefilter", prefilter_node)
    graph.add_node("classify", classify_node)
    graph.add_node("propose", propose_node)
    graph.add_edge(START, "fetch")
    graph.add_edge("fetch", "prefilter")
    graph.add_edge("prefilter", "classify")
    graph.add_edge("classify", "propose")
    graph.add_node("extract", extract_node)
    graph.add_conditional_edges("propose", route_after_propose, ["extract", END])
    graph.add_edge("extract", END)
    return graph.compile()


def collect_bill_items(state: AgentState) -> list[tuple[Email, Category, Bill]]:
    """(email, category, bill) for every extracted bill/receipt, in email order."""
    bills = state.get("bills", {})
    return [
        (email, state["classifications"][email.id].category, bills[email.id])
        for email in state["emails"]
        if email.id in bills
    ]
