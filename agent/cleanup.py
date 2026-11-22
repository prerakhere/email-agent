"""The clean-up list: mail that could go to the bin once the owner approves it.

For now only promotions are offered, never starred mail. Each offered email gets a short model
summary so the owner can decide on the approval page (a checkbox per email, all ticked to start).
This module only picks and summarises; moving mail is a separate, approved step. The bin keeps mail
for 30 days, so an approved clean-up can be undone.
"""

from langchain_core.runnables import Runnable
from pydantic import BaseModel, computed_field

from agent.digest_config import DigestSection
from agent.nodes.summarize import summarize_emails
from agent.schemas import Category, Email, Proposal

CLEANUP_CATEGORIES = [Category.PROMOTIONS]
MAX_CLEANUP_ITEMS = (
    50  # a heavy day can't turn into dozens of summary requests; the rest stay labelled
)
CLEANUP_SECTION = DigestSection(
    title="Clean-up",
    categories=CLEANUP_CATEGORIES,
    style=(
        "Promotional emails the owner may move to the bin. Name the brand, what is on offer and "
        "any deadline, so the owner can decide whether to keep it."
    ),
    body_chars=1000,
)


class CleanupItem(BaseModel):
    email_id: str
    sender: str
    subject: str
    summary: str  # the model's summary, or the subject line when it gave none


class CleanupList(BaseModel):
    items: list[CleanupItem]

    @computed_field
    @property
    def count(self) -> int:
        return len(self.items)

    @property
    def email_ids(self) -> list[str]:
        return [item.email_id for item in self.items]


def build_cleanup(
    proposals: list[Proposal], emails: list[Email], summarizer: Runnable
) -> CleanupList | None:
    """This run's promotions that are not starred, each with a summary; None when there are none.

    Proposals already leave out mail the owner filed themselves, so that mail is never offered."""
    offered = {
        p.email_id
        for p in proposals
        if p.category in CLEANUP_CATEGORIES and not p.starred
    }
    picked = [e for e in emails if e.id in offered][:MAX_CLEANUP_ITEMS]
    if not picked:
        return None
    summaries = summarize_emails(picked, CLEANUP_SECTION, summarizer)
    return CleanupList(
        items=[
            CleanupItem(
                email_id=s.email_id,
                sender=s.sender,
                subject=s.subject,
                summary=s.summary,
            )
            for s in summaries
        ]
    )
