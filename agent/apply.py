"""Phase 3: turn proposals into real Gmail changes, safely.

Defaults to a dry run: nothing is sent to Gmail (not even label creation). Mail that needs a
human eye is never moved out of the inbox: Important, Needs-Review and starred stay put.
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


def _skip_reason(proposal: Proposal) -> str | None:
    if proposal.starred:
        return "starred mail stays in the inbox"
    return NEVER_MOVE.get(proposal.category)


def apply_proposals(
    proposals: list[Proposal], gmail, dry_run: bool = True
) -> ApplyResult:
    result = ApplyResult()
    for proposal in proposals:
        reason = _skip_reason(proposal)
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
        gmail.move_to_label(proposal.email_id, label_ids[proposal.label])
        result.moved.append(proposal)
    return result
