"""Assemble the digest: route each email to its section, then summarise what will be shown.

Pure orchestration over the config and the summarisers; it sends nothing and writes nothing.
Only mail that will actually appear is sent to the model: a per-email section summarises its
newest `max_items` and just counts the rest, a group section gets one line, a table section needs
no model at all (its rows come from amounts already extracted), and mail whose category no section
covers is only counted.
"""

from datetime import datetime
from typing import Literal

from langchain_core.runnables import Runnable
from pydantic import BaseModel, Field

from agent.digest_config import DigestConfig, DigestSection
from agent.digest_tables import (
    EmailRef,
    Locale,
    TableData,
    bills_table,
    money_table,
    transactions_table,
)
from agent.nodes.summarize import (
    EmailSummary,
    GroupSummary,
    summarize_emails,
    summarize_group,
)
from agent.nodes.transactions import Transaction
from agent.profile import Profile
from agent.schemas import Bill, Classification, Email


class SectionSummary(BaseModel):
    title: str
    mode: Literal["per_email", "group", "table"]
    count: int  # every email in the section
    items: list[EmailSummary] = Field(
        default_factory=list
    )  # per_email: the newest max_items
    omitted: int = 0  # per_email: emails beyond max_items that were not summarised
    group: GroupSummary | None = None  # group mode
    table: TableData | None = None  # table mode
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
    classifications: dict[str, Classification],
    bills: dict[str, Bill],
    transactions: dict[str, Transaction],
    now: datetime | None,
    locale: Locale,
) -> SectionSummary:
    ordered = _newest_first(emails)
    if section.mode == "table":
        if section.table == "money":
            table = money_table(
                ordered,
                classifications,
                bills,
                transactions,
                section.max_items,
                now,
                locale,
            )
        elif section.table == "bills":
            table = bills_table(
                ordered, classifications, bills, section.max_items, now, locale
            )
        else:
            table = transactions_table(ordered, transactions, section.max_items, locale)
        return SectionSummary(
            title=section.title, mode="table", count=len(ordered), table=table
        )
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
    bills: dict[str, Bill] | None = None,
    transactions: dict[str, Transaction] | None = None,
    now: datetime | None = None,
    profile: Profile | None = None,
) -> DigestContent:
    locale = Locale.from_profile(profile)
    by_section: dict[str, list[Email]] = {s.title: [] for s in config.sections}
    other = 0
    for email in emails:
        section = config.section_for(classifications[email.id].category)
        if section is None:
            other += 1
        else:
            by_section[section.title].append(email)
    sections = [
        _summarise_section(
            s,
            by_section[s.title],
            per_email_chain,
            group_chain,
            classifications,
            bills or {},
            transactions or {},
            now,
            locale,
        )
        for s in config.sections
        if by_section[s.title]
    ]
    return DigestContent(sections=sections, other_count=other, total=len(emails))
