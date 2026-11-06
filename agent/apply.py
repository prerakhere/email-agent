"""Phase 3: turn proposals into real Gmail changes, safely.

Defaults to a dry run: nothing is sent to Gmail (not even label creation).
Defaults to keep_in_inbox: mail is only LABELLED and stays in the inbox, so every email can be
labelled safely. Only when mail leaves the inbox (keep_in_inbox=False) do Important, Needs-Review
and starred mail stay put, because those need a human eye.
"""

from dataclasses import dataclass, field

from agent.schemas import Category, Proposal

NEVER_MOVE = {
    Category.IMPORTANT: "important mail stays in the inbox",
    Category.NEEDS_REVIEW: "needs review: stays in the inbox",
}


@dataclass
class ApplyResult:
    planned: list[Proposal] = field(default_factory=list)  # eligible to move
    moved: list[Proposal] = field(
        default_factory=list
    )  # actually moved (empty on dry run)
    skipped: list[tuple[Proposal, str]] = field(default_factory=list)  # (proposal, why)
    keep_in_inbox: bool = False  # True: labels were only added, INBOX untouched


def _skip_reason(proposal: Proposal) -> str | None:
    if proposal.starred:
        return "starred mail stays in the inbox"
    return NEVER_MOVE.get(proposal.category)


def apply_proposals(
    proposals: list[Proposal],
    gmail,
    dry_run: bool = True,
    keep_in_inbox: bool = True,
) -> ApplyResult:
    result = ApplyResult(keep_in_inbox=keep_in_inbox)
    for proposal in proposals:
        reason = None if keep_in_inbox else _skip_reason(proposal)
        if reason:
            result.skipped.append((proposal, reason))
        else:
            result.planned.append(proposal)
    if dry_run:
        return result

    label_ids: dict[str, str] = {}  # look up / create each label once
    for proposal in result.planned:
        if proposal.label not in label_ids:
            label_ids[proposal.label] = gmail.ensure_label(proposal.label)
        label_id = label_ids[proposal.label]
        if keep_in_inbox:
            gmail.add_label(proposal.email_id, label_id)
        else:
            gmail.move_to_label(proposal.email_id, label_id)
        result.moved.append(proposal)
    return result
