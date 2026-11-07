"""What the daily digest contains, kept out of the code so it can change with your life.

A digest is a list of sections. Each section says which categories of mail it covers, how to
summarise them (plain-English `style`, handed to the model), whether to write one summary per
email or one for the whole group, and how many items to show. Mail whose category is in no
section only appears as a count in an "Everything else" line.

To change the digest, copy the defaults into `digest.toml` at the repo root (gitignored) and edit:

    [[sections]]
    title = "Work"
    categories = ["important", "job_alerts"]
    style = "List action points and deadlines."
    mode = "per_email"     # or "group"
    max_items = 10
    body_chars = 1500      # how much of each email the model reads (200 to 3000)

With no `digest.toml`, DEFAULT_CONFIG is used. Adding a brand-new CATEGORY of mail is a small
code change (agent/schemas.py); everything else is just this file.
"""

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from agent.gmail_client import BODY_PREVIEW_CHARS
from agent.schemas import Category


class DigestSection(BaseModel):
    title: str = Field(min_length=1)
    categories: list[Category] = Field(min_length=1)
    style: str = ""  # how the model should summarise this section
    mode: Literal["per_email", "group"] = "per_email"
    max_items: int = Field(default=10, ge=1)
    # How much of each email's body the model reads (after redaction): more costs more tokens.
    body_chars: int = Field(default=1500, ge=200, le=BODY_PREVIEW_CHARS)


class DigestConfig(BaseModel):
    sections: list[DigestSection] = Field(min_length=1)

    @model_validator(mode="after")
    def _each_category_in_one_section(self) -> "DigestConfig":
        seen: dict[Category, str] = {}
        for section in self.sections:
            for category in section.categories:
                if category in seen:
                    raise ValueError(
                        f"category {category.value!r} is in more than one section "
                        f"({seen[category]!r} and {section.title!r})"
                    )
                seen[category] = section.title
        return self

    def section_for(self, category: Category) -> DigestSection | None:
        return next((s for s in self.sections if category in s.categories), None)


DEFAULT_CONFIG = DigestConfig(
    sections=[
        DigestSection(
            title="Important",
            categories=[Category.IMPORTANT],
            style=(
                "One or two sentences per email. For recruiter or job-related mail list the "
                "action points (reply needed, deadline, interview, documents to send)."
            ),
            max_items=15,
        ),
        DigestSection(
            title="Bills and receipts",
            categories=[Category.BILLS, Category.RECEIPTS],
            style="Biller, amount and due date if any. Say what each mail is for.",
        ),
        DigestSection(
            title="Job alerts",
            categories=[Category.JOB_ALERTS],
            style="Give the count and the most relevant roles (title and company).",
            mode="group",
            max_items=5,
        ),
        DigestSection(
            title="Newsletters",
            categories=[Category.NEWSLETTERS],
            style="Two or three key points. Skip pure promotion.",
            body_chars=3000,  # the key points of a newsletter sit lower down
        ),
        DigestSection(
            title="Promotions",
            categories=[Category.PROMOTIONS],
            style="A short roundup: the count, and the notable brands or offers in a line or two.",
            mode="group",
            max_items=5,
        ),
        DigestSection(
            title="Notifications",
            categories=[Category.NOTIFICATIONS],
            style="A short roundup: the count and what the notifications were about.",
            mode="group",
            max_items=5,
        ),
        DigestSection(
            title="Needs review",
            categories=[Category.NEEDS_REVIEW],
            style="One line on what the mail is and why it was unclear.",
        ),
    ]
)


def load_digest_config(path: Path) -> DigestConfig:
    """The config in `path` (TOML), or the defaults when the file does not exist."""
    if not path.exists():
        return DEFAULT_CONFIG
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"{path.name} is not valid TOML: {error}") from error
    return DigestConfig(**data)
