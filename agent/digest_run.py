"""Create the digest for a time window: gather, classify, summarise and render.

Reads Gmail and calls the model, but sends and changes nothing: delivering the email is a separate,
lock-guarded step. Mail that already carries a label keeps its label's category; the rest is
classified, exactly as for labelling.
"""

from datetime import datetime

from langchain_core.runnables import Runnable

from agent.digest import DigestContent, build_digest
from agent.digest_config import DigestConfig
from agent.digest_email import RenderedDigest, render_digest
from agent.graph import build_graph
from agent.schemas import Category


def create_digest(
    gmail,
    rules: dict[str, Category],
    config: DigestConfig,
    classifier: Runnable,
    summarizer: Runnable,
    group_summarizer: Runnable,
    since: datetime,
    until: datetime,
    max_results: int = 500,
    extractor: Runnable | None = None,
    transaction_extractor: Runnable | None = None,
) -> tuple[DigestContent, RenderedDigest]:
    graph = build_graph(
        gmail,
        rules,
        classifier,
        since=since,
        extractor=extractor,
        transaction_extractor=transaction_extractor,
        max_results=max_results,
    )
    state = graph.invoke({})
    content = build_digest(
        state["emails"],
        state["classifications"],
        config,
        summarizer,
        group_summarizer,
        bills=state.get("bills"),
        transactions=state.get("transactions"),
        now=until,
    )
    return content, render_digest(content, since, until)
