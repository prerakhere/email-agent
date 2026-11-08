"""Helpers shared by the steps that show email text to a model and read its reply.

render_email_blocks: the request text, one numbered <email id=N> block per email. Subject and body are
redacted first (amounts are kept) and the body is trimmed after redaction, so a number cut at the
boundary cannot leak partial digits. The sender is kept as is.

strip_links: model output is untrusted (a hostile email can steer it), so any URL it writes is
removed before it reaches the digest, which adds its own links built from message ids.
"""

import re

from agent.redact import redact
from agent.schemas import Email

_LINK = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)


def strip_links(text: str) -> str:
    """Drop URLs and tidy spaces."""
    return " ".join(_LINK.sub("", text).split())


def render_email_blocks(emails: list[Email], body_chars: int) -> str:
    """One numbered block per email (ids start at 1), redacted and trimmed."""
    return "\n\n".join(
        f"<email id={n}>\n"
        f"From: {email.sender}\n"
        f"Subject: {redact(email.subject)}\n"
        f"Body start:\n{redact(email.body_preview)[:body_chars]}\n"
        f"</email>"
        for n, email in enumerate(emails, start=1)
    )
