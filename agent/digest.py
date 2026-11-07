"""Assemble the digest: route each email to its section, then summarise what will be shown.

Pure orchestration over the config and the two summarisers; it sends nothing and writes nothing.
Only mail that will actually appear is sent to the model: a per-email section summarises its
newest `max_items` and just counts the rest, and mail whose category no section covers is only
counted.
"""

from typing import Literal

from langchain_core.runnables import Runnable
from pydantic import BaseModel, Field

from agent.digest_config import DigestConfig, DigestSection
from agent.nodes.summarize import (
    EmailSummary,
    GroupSummary,
    summarize_emails,
    summarize_group,
)
from agent.schemas import Classification, Email


class EmailRef(BaseModel):
    """Enough to show a clickable line for an email in a group section."""

    email_id: str
    sender: str
    subject: str


class SectionSummary(BaseModel):
    title: str
    mode: Literal["per_email", "group"]
    count: int  # every email in the section
    items: list[EmailSummary] = Field(
        default_factory=list
    )  # per_email: the newest max_items
    omitted: int = 0  # per_email: emails beyond max_items that were not summarised
    group: GroupSummary | None = None  # group mode
    refs: list[EmailRef] = Field(
        default_factory=list
    )  # group mode: first max_items emails


class DigestContent(BaseModel):
    sections: list[SectionSummary]  # config order; empty sections are left out
    other_count: int  # mail in a category no section covers
    total: int  # every email considered


def _newest_first(emails: list[Email]) -> list[Email]:
    """Newest first; mail with no date last. The sort is stable, so ties keep arrival order."""
    return sorted(
        emails,
        key=lambda e: (
            e.received_at is None,
            -(e.received_at.timestamp() if e.received_at else 0),
        ),
    )


def _summarise_section(
    section: DigestSection,
    emails: list[Email],
    per_email_chain: Runnable,
    group_chain: Runnable,
) -> SectionSummary:
    ordered = _newest_first(emails)
    if section.mode == "group":
        return SectionSummary(
            title=section.title,
            mode="group",
            count=len(ordered),
            group=summarize_group(ordered, section, group_chain),
            refs=[
                EmailRef(email_id=e.id, sender=e.sender, subject=e.subject)
                for e in ordered[: section.max_items]
            ],
        )
    shown = ordered[: section.max_items]
    return SectionSummary(
        title=section.title,
        mode="per_email",
        count=len(ordered),
        items=summarize_emails(shown, section, per_email_chain),
        omitted=len(ordered) - len(shown),
    )


def build_digest(
    emails: list[Email],
    classifications: dict[str, Classification],
    config: DigestConfig,
    per_email_chain: Runnable,
    group_chain: Runnable,
) -> DigestContent:
    by_section: dict[str, list[Email]] = {s.title: [] for s in config.sections}
    other = 0
    for email in emails:
        section = config.section_for(classifications[email.id].category)
        if section is None:
            other += 1
        else:
            by_section[section.title].append(email)
    sections = [
        _summarise_section(s, by_section[s.title], per_email_chain, group_chain)
        for s in config.sections
        if by_section[s.title]
    ]
    return DigestContent(sections=sections, other_count=other, total=len(emails))
