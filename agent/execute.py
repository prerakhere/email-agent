"""The real (non-dry-run) step: log bills to the sheet, then label mail.

Order matters. Already-labelled mail is skipped on later runs, so if labels were applied first and
the sheet write then failed, that bill would never be extracted again. Writing the sheet FIRST
means a failure leaves the mail unlabelled and the next run simply retries.
"""

from dataclasses import dataclass, field

from agent.apply import ApplyResult, apply_proposals
from agent.graph import AgentState, collect_bill_items


@dataclass
class RunOutcome:
    rows_added: list[str] = field(
        default_factory=list
    )  # email ids appended to the sheet
    labelled: ApplyResult | None = None  # None when labelling was not requested


def execute_run(
    state: AgentState,
    gmail,
    sheets,
    label: bool = True,
    keep_in_inbox: bool = True,
) -> RunOutcome:
    """`sheets` may be None (bills are then not logged); `label=False` leaves Gmail untouched."""
    outcome = RunOutcome()
    items = collect_bill_items(state)
    if items and sheets is not None:
        outcome.rows_added = sheets.log_bills(
            items
        )  # raises on failure: no labelling then
    if label:
        outcome.labelled = apply_proposals(
            state["proposals"], gmail, dry_run=False, keep_in_inbox=keep_in_inbox
        )
    return outcome
