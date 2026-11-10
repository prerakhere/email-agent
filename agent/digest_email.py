"""Turn a DigestContent into the email: a subject, an HTML body and a plain-text body.

Safety rules, because the text comes from strangers' emails and from a model:
- every piece of dynamic text is HTML-escaped;
- every link is built here from a message id and points at mail.google.com; a URL the model or a
  sender wrote can never become a link.
Times are shown in Indian time (the digest is for one person in India).
"""

import re
from dataclasses import dataclass
from datetime import datetime
from email.utils import parseaddr
from html import escape
from urllib.parse import quote
from zoneinfo import ZoneInfo

from agent.digest import DigestContent, SectionSummary
from agent.digest_tables import EmailRef, TableData
from agent.nodes.summarize import EmailSummary
from agent.sheets_client import email_link

LOCAL_TZ = ZoneInfo("Asia/Kolkata")
NO_SUMMARY = "Summary unavailable"
MAX_LINE_CHARS = 160  # every summary is one line
MAX_HTML_BYTES = 90_000  # Gmail clips a message at about 102 KB; stay well under it
SHORTENED_NOTE = "Shortened to fit Gmail's size limit; open Gmail for the rest."
# (items per per_email section, links per group, rows per table, unlisted per table) per level
SHRINK_LEVELS = [(15, 3, 40, 5), (5, 0, 15, 0)]
# A summary that only says the mail could not be read tells the reader nothing.
_USELESS_SUMMARY = re.compile(
    r"not (be )?(viewable|displayed|visible)|unable to (view|display|read)"
    r"|(can(no|')t|could ?n[o']t) be (viewed|displayed|read)",
    re.IGNORECASE,
)


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


def _sender_name(sender: str) -> str:
    """'Jane <jane@corp.com>' -> 'Jane'; a bare address stays as it is."""
    name, address = parseaddr(sender)
    return name or address or sender


def _one_line(text: str) -> str:
    """Collapse whitespace and cut to one line at a word boundary, ending in an ellipsis."""
    flat = " ".join(text.split())
    if len(flat) <= MAX_LINE_CHARS:
        return flat
    cut = flat[: MAX_LINE_CHARS - 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return cut + "…"


def _is_useless(item: EmailSummary) -> bool:
    return not item.fallback and bool(_USELESS_SUMMARY.search(item.summary))


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _shrink(content: DigestContent, level: int) -> DigestContent:
    """A copy with each list trimmed harder; what is cut is counted, never silently lost."""
    max_items, max_refs, max_rows, max_unlisted = SHRINK_LEVELS[level]
    shrunk = content.model_copy(deep=True)
    for section in shrunk.sections:
        if section.mode == "per_email":
            cut = len(section.items) - max_items
            if cut > 0:
                section.items = section.items[:max_items]
                section.omitted += cut
        elif section.mode == "group":
            section.refs = section.refs[:max_refs]
        elif section.table is not None:
            cut = len(section.table.rows) - max_rows
            if cut > 0:
                section.table.rows = section.table.rows[:max_rows]
                section.table.omitted += cut
            section.table.unlisted = section.table.unlisted[:max_unlisted]
    return shrunk


def render_digest(
    content: DigestContent, since: datetime, until: datetime
) -> RenderedDigest:
    local_end = until.astimezone(LOCAL_TZ)
    subject = f"Inbox digest, {local_end.day} {local_end:%b}: {_plural(content.total, 'email')}"
    window = f"{_when(since)} to {_when(until)}"
    shown, note = content, False
    html = _render_html(shown, window, note)
    for level in range(len(SHRINK_LEVELS)):
        if len(html.encode()) <= MAX_HTML_BYTES:
            break
        shown, note = _shrink(content, level), True
        html = _render_html(shown, window, note)
    return RenderedDigest(
        subject=subject, text=_render_text(shown, window, note), html=html
    )


def _important_count(content: DigestContent) -> int:
    return sum(s.count for s in content.sections if s.title == "Important")


def _due_soon_count(content: DigestContent) -> int:
    return sum(
        1
        for s in content.sections
        if s.table is not None
        for row in s.table.rows
        if row.highlight
    )


def _headline(content: DigestContent) -> str:
    """One human line: what is important and what is due soon. No model call."""
    if content.total == 0:
        return "No new mail"
    important, due = _important_count(content), _due_soon_count(content)
    parts = []
    if important:
        parts.append(f"{important} important")
    if due:
        parts.append(f"{due} due soon")
    if not parts:
        parts.append("Nothing urgent")
    return " · ".join(parts)


# ---- plain text ----


def _text_entry(item: EmailSummary) -> list[str]:
    lines = [
        f"* {item.subject} - {_sender_name(item.sender)}",
        f"  {_link(item.email_id)}",
    ]
    if item.fallback:
        lines.append(f"  {NO_SUMMARY}")
    elif not _is_useless(item):
        lines.append(f"  {_one_line(item.summary)}")
    lines += [f"  - Action: {point}" for point in item.action_points]
    return lines


def _text_table(table: TableData) -> list[str]:
    lines = [table.summary, " | ".join(table.columns) + " | Mail"]
    for row in table.rows:
        mark = "! " if row.highlight else "  "
        lines.append(f"{mark}{' | '.join(row.cells)} | {_link(row.email_id)}")
    if table.omitted:
        lines.append(f"+{table.omitted} more not shown")
    if table.statements:
        lines.append("Statements:")
        for ref in table.statements:
            lines += [
                f"* {ref.subject} - {_sender_name(ref.sender)}",
                f"  {_link(ref.email_id)}",
            ]
    if table.unlisted:
        lines.append("No amount found:")
        for ref in table.unlisted:
            lines += [
                f"* {ref.subject} - {_sender_name(ref.sender)}",
                f"  {_link(ref.email_id)}",
            ]
    return lines


def _text_section(section: SectionSummary) -> list[str]:
    lines = ["", f"{section.title} ({section.count})", "-" * 30]
    if section.mode == "table" and section.table is not None:
        lines += _text_table(section.table)
    elif section.mode == "group":
        group = section.group
        lines.append(
            NO_SUMMARY if group is None or group.fallback else _one_line(group.summary)
        )
        for ref in section.refs:
            lines += [
                f"* {ref.subject} - {_sender_name(ref.sender)}",
                f"  {_link(ref.email_id)}",
            ]
        if section.count > len(section.refs):
            lines.append(f"+{section.count - len(section.refs)} more not shown")
    else:
        for item in section.items:
            lines += _text_entry(item)
        if section.omitted:
            lines.append(f"+{section.omitted} more not shown")
    return lines


def _render_text(content: DigestContent, window: str, shortened: bool = False) -> str:
    lines = [
        "Inbox digest",
        f"{window} ({_plural(content.total, 'email')})",
        _headline(content),
    ]
    if content.total == 0:
        lines += ["", "No new mail in this window."]
    for section in content.sections:
        lines += _text_section(section)
    if content.other_count:
        lines += [
            "",
            f"Plus {_plural(content.other_count, 'other email')} not summarised.",
        ]
    if shortened:
        lines += ["", SHORTENED_NOTE]
    return "\n".join(lines) + "\n"


# ---- HTML ----

FONT = "-apple-system,Segoe UI,Arial,sans-serif"
# One colour per section, in order. Mid-tones on purpose: readable on light and dark backgrounds,
# and the email never sets a background of its own, so the mail client picks light or dark.
SECTION_COLOURS = [
    "#2563eb",
    "#d97706",
    "#059669",
    "#7c3aed",
    "#db2777",
    "#0891b2",
    "#65a30d",
    "#dc2626",
]
MUTED = "color:#888888"
TILE_BORDER = "#9ca3af"


def _anchor(email_id: str, label: str) -> str:
    return f'<a href="{escape(_link(email_id), quote=True)}">{escape(label)}</a>'


def _initial(sender: str) -> str:
    for char in _sender_name(sender):
        if char.isalpha():
            return char.upper()
    return "?"


def _avatar(sender: str, colour: str) -> str:
    return (
        f'<div style="width:32px;height:32px;line-height:32px;border-radius:16px;'
        f'background:{colour};color:#ffffff;text-align:center;font-weight:bold">'
        f"{escape(_initial(sender))}</div>"
    )


def _html_entry(item: EmailSummary, colour: str) -> str:
    if item.fallback:
        body = f'<p style="margin:4px 0 0"><i>{NO_SUMMARY}</i></p>'
    elif _is_useless(item):
        body = ""
    else:
        body = f'<p style="margin:4px 0 0">{escape(_one_line(item.summary))}</p>'
    points = ""
    if item.action_points:
        points = (
            '<ul style="margin:4px 0 0;padding-left:18px">'
            + "".join(f"<li>{escape(p)}</li>" for p in item.action_points)
            + "</ul>"
        )
    return (
        '<table role="presentation" width="100%" style="border-collapse:collapse"><tr>'
        f'<td width="44" valign="top" style="padding:12px 12px 12px 0">{_avatar(item.sender, colour)}</td>'
        f'<td valign="top" style="padding:12px 0 12px 0">'
        f"<b>{_anchor(item.email_id, item.subject)}</b> "
        f'<span style="{MUTED}">{escape(_sender_name(item.sender))}</span>{body}{points}</td>'
        "</tr></table>"
    )


def _html_ref(ref: EmailRef) -> str:
    return (
        f'<li style="padding:6px 0">{_anchor(ref.email_id, ref.subject)} '
        f'<span style="{MUTED}">{escape(_sender_name(ref.sender))}</span></li>'
    )


def _align(column: str) -> str:
    return "right" if column == "Amount" else "left"


def _html_table(table: TableData) -> str:
    header = (
        "<tr>"
        + "".join(
            f'<th style="text-align:{_align(c)};padding:6px 8px 6px {0 if i == 0 else 8}px;'
            f'{MUTED};font-size:12px">{escape(c)}</th>'
            for i, c in enumerate(table.columns)
        )
        + "</tr>"
    )
    rows = []
    for row in table.rows:
        cells = []
        for index, (column, cell) in enumerate(
            zip(table.columns, row.cells, strict=False)
        ):
            inner = (
                _anchor(row.email_id, cell)
                if index == table.link_column
                else escape(cell)
            )
            if row.highlight:
                inner = f"<b>{inner}</b>"
            cells.append(
                f'<td style="text-align:{_align(column)};'
                f'padding:12px 8px 12px {0 if index == 0 else 8}px">{inner}</td>'
            )
        rows.append(f"<tr>{''.join(cells)}</tr>")
    parts = [
        f'<p style="margin:8px 0">{escape(table.summary)}</p>',
        '<table width="100%" style="border-collapse:collapse;font-size:14px">'
        + header
        + "".join(rows)
        + "</table>",
    ]
    if table.omitted:
        parts.append(f'<p style="{MUTED}">+{table.omitted} more not shown</p>')
    if table.statements:
        parts.append(
            f'<p style="{MUTED}">Statements:</p>'
            '<ul style="margin:0;padding-left:18px">'
            + "".join(_html_ref(r) for r in table.statements)
            + "</ul>"
        )
    if table.unlisted:
        parts.append(
            f'<p style="{MUTED}">No amount found:</p>'
            '<ul style="margin:0;padding-left:18px">'
            + "".join(_html_ref(r) for r in table.unlisted)
            + "</ul>"
        )
    return "".join(parts)


def _html_section(section: SectionSummary, colour: str) -> str:
    heading = (
        f'<h2 style="font-size:18px;margin:28px 0 8px;padding-bottom:6px;'
        f'border-bottom:2px solid {colour}">{escape(section.title)} ({section.count})</h2>'
    )
    parts = [heading]
    if section.mode == "table" and section.table is not None:
        parts.append(_html_table(section.table))
    elif section.mode == "group":
        group = section.group
        text = (
            NO_SUMMARY if group is None or group.fallback else _one_line(group.summary)
        )
        parts.append(f'<p style="margin:8px 0">{escape(text)}</p>')
        if section.refs:
            parts.append(
                '<ul style="margin:0;padding-left:18px">'
                + "".join(_html_ref(r) for r in section.refs)
                + "</ul>"
            )
        if section.count > len(section.refs):
            parts.append(
                f'<p style="{MUTED}">+{section.count - len(section.refs)} more not shown</p>'
            )
    else:
        parts += [_html_entry(item, colour) for item in section.items]
        if section.omitted:
            parts.append(f'<p style="{MUTED}">+{section.omitted} more not shown</p>')
    return "".join(parts)


def _tile(number: int, label: str) -> str:
    return (
        f'<td width="33%" style="text-align:center;padding:12px 4px;'
        f'border:1px solid {TILE_BORDER};border-radius:8px">'
        f'<div style="font-size:28px;font-weight:bold">{number}</div>'
        f'<div style="font-size:12px;{MUTED}">{label}</div></td>'
    )


def _tiles(content: DigestContent) -> str:
    return (
        '<table role="presentation" width="100%" '
        'style="border-collapse:separate;border-spacing:6px 0;margin:12px 0"><tr>'
        + _tile(content.total, "Emails")
        + _tile(_important_count(content), "Important")
        + _tile(_due_soon_count(content), "Due soon")
        + "</tr></table>"
    )


def _render_html(content: DigestContent, window: str, shortened: bool = False) -> str:
    line = _headline(content)
    body = [
        # Shown by mail apps as the grey preview next to the subject; hidden in the email itself.
        (
            '<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;'
            f'font-size:1px;line-height:1px">{escape(line)}{"&nbsp;&zwnj;" * 40}</div>'
        ),
        '<h1 style="font-size:24px;margin:0 0 4px">Inbox digest</h1>',
        f'<p style="margin:0;font-size:13px;{MUTED}">{escape(window)}</p>',
        f'<p style="font-size:18px;font-weight:bold;margin:12px 0 0">{escape(line)}</p>',
        _tiles(content),
    ]
    if content.total == 0:
        body.append("<p>No new mail in this window.</p>")
    body += [
        _html_section(section, SECTION_COLOURS[index % len(SECTION_COLOURS)])
        for index, section in enumerate(content.sections)
    ]
    if content.other_count:
        body.append(
            f'<p style="{MUTED}">Plus {_plural(content.other_count, "other email")} '
            "not summarised.</p>"
        )
    if shortened:
        body.append(f'<p style="{MUTED}"><i>{escape(SHORTENED_NOTE)}</i></p>')
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light dark">'
        '<meta name="supported-color-schemes" content="light dark">'
        "<title>Inbox digest</title></head>"
        '<body style="margin:0;padding:16px">'
        f'<div style="font-family:{FONT};max-width:600px;margin:0 auto;line-height:1.45">'
        + "".join(body)
        + "</div></body></html>"
    )
