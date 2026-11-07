"""Turn a DigestContent into the email: a subject, an HTML body and a plain-text body.

Safety rules, because the text comes from strangers' emails and from a model:
- every piece of dynamic text is HTML-escaped;
- every link is built here from a message id and points at mail.google.com; a URL the model or a
  sender wrote can never become a link.
Times are shown in Indian time (the digest is for one person in India).
"""

from dataclasses import dataclass
from datetime import datetime
from html import escape
from urllib.parse import quote
from zoneinfo import ZoneInfo

from agent.digest import DigestContent, EmailRef, SectionSummary
from agent.nodes.summarize import EmailSummary
from agent.sheets_client import email_link

LOCAL_TZ = ZoneInfo("Asia/Kolkata")
NO_SUMMARY = "Summary unavailable"


@dataclass
class RenderedDigest:
    subject: str
    text: str
    html: str


def _when(moment: datetime) -> str:
    local = moment.astimezone(LOCAL_TZ)
    return f"{local.day} {local:%b}, {local.hour % 12 or 12}:{local:%M} {local:%p}"


def _link(email_id: str) -> str:
    return email_link(quote(email_id, safe=""))


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def render_digest(
    content: DigestContent, since: datetime, until: datetime
) -> RenderedDigest:
    local_end = until.astimezone(LOCAL_TZ)
    subject = f"Inbox digest, {local_end.day} {local_end:%b}: {_plural(content.total, 'email')}"
    window = f"{_when(since)} to {_when(until)}"
    return RenderedDigest(
        subject=subject,
        text=_render_text(content, window),
        html=_render_html(content, window),
    )


# ---- plain text ----


def _text_entry(item: EmailSummary) -> list[str]:
    lines = [f"* {item.subject} - {item.sender}", f"  {_link(item.email_id)}"]
    lines.append(f"  {NO_SUMMARY}" if item.fallback else f"  {item.summary}")
    lines += [f"  - Action: {point}" for point in item.action_points]
    return lines


def _text_section(section: SectionSummary) -> list[str]:
    lines = ["", f"{section.title} ({section.count})", "-" * 30]
    if section.mode == "group":
        group = section.group
        lines.append(NO_SUMMARY if group is None or group.fallback else group.summary)
        for ref in section.refs:
            lines += [f"* {ref.subject} - {ref.sender}", f"  {_link(ref.email_id)}"]
    else:
        for item in section.items:
            lines += _text_entry(item)
        if section.omitted:
            lines.append(f"+{section.omitted} more not shown")
    return lines


def _render_text(content: DigestContent, window: str) -> str:
    lines = ["Inbox digest", f"{window} ({_plural(content.total, 'email')})"]
    if content.total == 0:
        lines += ["", "No new mail in this window."]
    for section in content.sections:
        lines += _text_section(section)
    if content.other_count:
        lines += [
            "",
            f"Plus {_plural(content.other_count, 'other email')} not summarised.",
        ]
    return "\n".join(lines) + "\n"


# ---- HTML ----


def _anchor(email_id: str, label: str) -> str:
    return f'<a href="{escape(_link(email_id), quote=True)}">{escape(label)}</a>'


def _html_entry(item: EmailSummary) -> str:
    body = (
        f"<p><i>{NO_SUMMARY}</i></p>"
        if item.fallback
        else f"<p>{escape(item.summary)}</p>"
    )
    points = ""
    if item.action_points:
        points = (
            "<ul>"
            + "".join(f"<li>{escape(p)}</li>" for p in item.action_points)
            + "</ul>"
        )
    return (
        f"<div>{_anchor(item.email_id, item.subject)} "
        f'<span style="color:#666">{escape(item.sender)}</span>{body}{points}</div>'
    )


def _html_ref(ref: EmailRef) -> str:
    return (
        f"<li>{_anchor(ref.email_id, ref.subject)} "
        f'<span style="color:#666">{escape(ref.sender)}</span></li>'
    )


def _html_section(section: SectionSummary) -> str:
    parts = [f"<h2>{escape(section.title)} ({section.count})</h2>"]
    if section.mode == "group":
        group = section.group
        text = NO_SUMMARY if group is None or group.fallback else group.summary
        parts.append(f"<p>{escape(text)}</p>")
        if section.refs:
            parts.append("<ul>" + "".join(_html_ref(r) for r in section.refs) + "</ul>")
    else:
        parts += [_html_entry(item) for item in section.items]
        if section.omitted:
            parts.append(f"<p>+{section.omitted} more not shown</p>")
    return "".join(parts)


def _render_html(content: DigestContent, window: str) -> str:
    body = [
        "<h1>Inbox digest</h1>",
        f'<p style="color:#666">{escape(window)} ({_plural(content.total, "email")})</p>',
    ]
    if content.total == 0:
        body.append("<p>No new mail in this window.</p>")
    body += [_html_section(section) for section in content.sections]
    if content.other_count:
        body.append(
            f"<p>Plus {_plural(content.other_count, 'other email')} not summarised.</p>"
        )
    return (
        '<div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;'
        'max-width:640px;line-height:1.45">' + "".join(body) + "</div>"
    )
