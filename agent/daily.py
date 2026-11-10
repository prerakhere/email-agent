"""The daily run: classify once, then log bills, label mail and send the digest.

One pass over the window: the model classifies each unlabelled mail a single time, and the labels,
the bill rows and the digest all come from that one result.

The three actions are INDEPENDENT. A failure in one (say the Sheet is down) must not stop the
digest, which is the main deliverable, so each is attempted on its own and its failure recorded in
`errors` as "step: ErrorType". The error MESSAGE is deliberately not kept: it could contain email
text, and logs must never hold any. Failures before the actions (fetching, classifying,
summarising) are not caught: with no digest to send there is nothing to protect, so they raise.

Without `apply` nothing is changed or sent: the digest is still built, and the counts of what would
happen are returned. An empty window still sends a "No new mail" digest, so a missing email means
something broke.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from langchain_core.runnables import Runnable

from agent.apply import ApplyResult, apply_proposals
from agent.digest import DigestContent, build_digest
from agent.digest_config import DigestConfig
from agent.digest_email import RenderedDigest, render_digest
from agent.graph import build_graph, collect_bill_items
from agent.profile import Profile
from agent.schemas import Bill, Category, Email, Proposal

log = logging.getLogger("gmail_agent.daily")


@dataclass
class DailyPlan:
    """Everything decided for the window, before anything is changed or sent."""

    content: DigestContent
    rendered: RenderedDigest
    proposals: list[Proposal]  # labels to add (only for mail without one)
    bill_items: list[tuple[Email, Category, Bill]]
    keep_in_inbox: bool

    @property
    def planned_labels(self) -> int:
        return len(self._label_plan().planned)

    @property
    def planned_rows(self) -> int:
        return len(self.bill_items)

    def _label_plan(self) -> ApplyResult:
        # A dry run: decides what would be labelled and makes no Gmail call.
        return apply_proposals(
            self.proposals, None, dry_run=True, keep_in_inbox=self.keep_in_inbox
        )


@dataclass
class DailyResult:
    plan: DailyPlan
    rows_added: list[str] = field(
        default_factory=list
    )  # email ids appended to the Sheet
    labelled: ApplyResult | None = None
    digest_message_id: str | None = None
    errors: list[str] = field(
        default_factory=list
    )  # "step: ErrorType", never a message

    @property
    def content(self) -> DigestContent:
        return self.plan.content

    @property
    def rendered(self) -> RenderedDigest:
        return self.plan.rendered

    @property
    def planned_labels(self) -> int:
        return self.plan.planned_labels

    @property
    def planned_rows(self) -> int:
        return self.plan.planned_rows


def prepare_daily(
    gmail,
    rules: dict[str, Category],
    config: DigestConfig,
    classifier: Runnable,
    extractor: Runnable,
    summarizer: Runnable,
    group_summarizer: Runnable,
    since: datetime,
    until: datetime,
    keep_in_inbox: bool = True,
    max_results: int = 500,
    transaction_extractor: Runnable | None = None,
    profile: Profile | None = None,
) -> DailyPlan:
    """Read the window, classify once, summarise and render. Changes and sends nothing."""
    graph = build_graph(
        gmail,
        rules,
        classifier,
        since=since,
        extractor=extractor,
        transaction_extractor=transaction_extractor,
        max_results=max_results,
        # The agent's own earlier labels are only guesses: re-check them with the current classifier
        # so improving the classifier improves the digest at once. The user's own folders stay trusted.
        trust_agent_labels=False,
        profile=profile,
    )
    # Each stage is logged (name and elapsed seconds only, never content) so a stall shows where:
    # the last line printed is the last stage that finished.
    started = time.monotonic()
    log.info("stage fetch started")
    state: dict = {}
    for update in graph.stream({}, stream_mode="updates"):
        for node, changes in update.items():
            state.update(changes)
            log.info("stage %s done after %.0fs", node, time.monotonic() - started)
    log.info("stage digest started")
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
    log.info("stage digest done after %.0fs", time.monotonic() - started)
    return DailyPlan(
        content=content,
        rendered=render_digest(content, since, until),
        proposals=state["proposals"],
        bill_items=collect_bill_items(state),
        keep_in_inbox=keep_in_inbox,
    )


def execute_daily(plan: DailyPlan, gmail, sheets) -> DailyResult:
    """Act on exactly this plan, with no further model calls: bills, then labels, then the digest.

    `sheets` may be None (bills are then skipped). Each action is attempted on its own.
    """
    result = DailyResult(plan=plan)

    def attempt(step: str, action: Callable[[], Any]) -> Any:
        try:
            return action()
        except Exception as error:  # noqa: BLE001 - isolating every failure is the point
            result.errors.append(f"{step}: {type(error).__name__}")  # never the message
            return None

    if plan.bill_items and sheets is not None:
        result.rows_added = (
            attempt("log_bills", lambda: sheets.log_bills(plan.bill_items)) or []
        )
    result.labelled = attempt(
        "apply_labels",
        lambda: apply_proposals(
            plan.proposals, gmail, dry_run=False, keep_in_inbox=plan.keep_in_inbox
        ),
    )
    result.digest_message_id = attempt(
        "send_digest",
        lambda: gmail.send_to_self(
            plan.rendered.subject, plan.rendered.text, plan.rendered.html
        ),
    )
    return result


def run_daily(
    gmail,
    sheets,
    rules: dict[str, Category],
    config: DigestConfig,
    classifier: Runnable,
    extractor: Runnable,
    summarizer: Runnable,
    group_summarizer: Runnable,
    since: datetime,
    until: datetime,
    apply: bool = False,
    keep_in_inbox: bool = True,
    max_results: int = 500,
    transaction_extractor: Runnable | None = None,
    profile: Profile | None = None,
) -> DailyResult:
    """prepare_daily, then execute_daily only when `apply` is set."""
    plan = prepare_daily(
        gmail,
        rules,
        config,
        classifier,
        extractor,
        summarizer,
        group_summarizer,
        since,
        until,
        keep_in_inbox=keep_in_inbox,
        max_results=max_results,
        transaction_extractor=transaction_extractor,
        profile=profile,
    )
    return execute_daily(plan, gmail, sheets) if apply else DailyResult(plan=plan)
