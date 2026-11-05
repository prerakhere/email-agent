"""The LangGraph pipeline (Phase 1, linear): fetch -> prefilter -> classify -> propose.

State is one shared typed dict. Each node is a plain function that returns only the keys it
changed; LangGraph merges those into the state. Dependencies (Gmail client, rules, LLM chain)
are injected so tests use fakes.
"""

from typing import TypedDict

from langchain_core.runnables import Runnable
from langgraph.graph import END, START, StateGraph

from agent.labels import resolve_label
from agent.nodes.classify import classify
from agent.nodes.prefilter import prefilter
from agent.schemas import Category, Classification, Email, Proposal


class AgentState(TypedDict, total=False):
    emails: list[Email]
    existing_labels: list[str]
    classifications: dict[str, Classification]  # keyed by email id
    proposals: list[Proposal]


def build_graph(
    gmail,
    rules: dict[str, Category],
    chain: Runnable,
    days: int = 3,
    max_results: int = 100,
):
    def fetch_node(state: AgentState) -> dict:
        return {
            "emails": gmail.fetch_recent(days=days, max_results=max_results),
            "existing_labels": gmail.list_label_names(),
        }

    def prefilter_node(state: AgentState) -> dict:
        decided = {}
        for email in state["emails"]:
            result = prefilter(email, rules)
            if result is not None:
                decided[email.id] = result
        return {"classifications": decided}

    def classify_node(state: AgentState) -> dict:
        # A returned key REPLACES the old value, so return the merged dict.
        classifications = dict(state["classifications"])
        for email in state["emails"]:
            if email.id not in classifications:  # only mail no rule decided
                classifications[email.id] = classify(email, chain)
        return {"classifications": classifications}

    def propose_node(state: AgentState) -> dict:
        proposals = []
        for email in state["emails"]:
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
                )
            )
        return {"proposals": proposals}

    graph = StateGraph(AgentState)
    graph.add_node("fetch", fetch_node)
    graph.add_node("prefilter", prefilter_node)
    graph.add_node("classify", classify_node)
    graph.add_node("propose", propose_node)
    graph.add_edge(START, "fetch")
    graph.add_edge("fetch", "prefilter")
    graph.add_edge("prefilter", "classify")
    graph.add_edge("classify", "propose")
    graph.add_edge("propose", END)
    return graph.compile()
