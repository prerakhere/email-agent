"""The approval page behind the digest's "Review and choose" button.

GET shows the paused thread's list: every email ticked, a Select all box, "Move selected to Bin"
and "Keep all". Opening it never changes anything (link scanners may open links on their own). Only
the form's POST acts, and it resumes the thread with the ticked ids. Both check the signed link.

Pure: the HTTP trigger in function_app.py passes the request in and sends the response out.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from urllib.parse import quote

from agent.approval import pending_items, resume_approval
from agent.approval_link import verify
from agent.cleanup import CleanupItem
from agent.sheets_client import email_link

HEADERS = {
    "Content-Type": "text/html; charset=utf-8",
    "Cache-Control": "no-store",
    # The page holds a signed link: never pass it on as a Referer when an email is opened in Gmail.
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    # Nothing loads from elsewhere, the form can only post back here, and no site can frame the page.
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    ),
}
LINK_FIELDS = ("t", "e", "s")

INVALID = "This link is not valid or has expired. Nothing was changed."
NOTHING_WAITING = (
    "Nothing is waiting here: this clean-up was already answered or has expired."
)


@dataclass
class WebResponse:
    status: int
    body: str
    headers: dict[str, str] = field(default_factory=lambda: dict(HEADERS))


def _document(title: str, content: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light dark">'
        f"<title>{escape(title)}</title></head>"
        '<body style="margin:0;padding:16px;font-family:-apple-system,Segoe UI,Arial,sans-serif">'
        f'<div style="max-width:640px;margin:0 auto;line-height:1.45">{content}</div>'
        "</body></html>"
    )


def _message(status: int, text: str) -> WebResponse:
    return WebResponse(
        status, _document("Clean-up", f"<h1>Clean-up</h1><p>{escape(text)}</p>")
    )


def _item(entry: CleanupItem) -> str:
    gmail = email_link(quote(entry.email_id, safe=""))
    return (
        '<li style="margin:0 0 14px">'
        f'<label><input type="checkbox" name="id" value="{escape(entry.email_id)}" class="item" checked> '
        f"<b>{escape(entry.subject)}</b></label>"
        f'<div style="color:#888888;font-size:13px">{escape(entry.sender)} · '
        f'<a href="{escape(gmail)}" target="_blank" rel="noopener noreferrer">Open in Gmail</a></div>'
        f"<div>{escape(entry.summary)}</div>"
        "</li>"
    )


def _list_page(items: list[CleanupItem], link: Mapping[str, str]) -> WebResponse:
    count = len(items)
    noun = "promotion" if count == 1 else "promotions"
    hidden = "".join(
        f'<input type="hidden" name="{key}" value="{escape(link[key])}">'
        for key in LINK_FIELDS
    )
    select_all = (
        '<label><input type="checkbox" id="select-all" checked onclick="'
        "for (const box of document.querySelectorAll('.item')) box.checked = this.checked"
        '"> <b>Select all</b></label>'
    )
    content = (
        "<h1>Clean-up</h1>"
        f"<p>{count} {noun} offered for the bin. Untick any you want to keep. Anything moved stays "
        "in Gmail's Bin for 30 days.</p>"
        f'<form method="post">{hidden}'
        f"<p>{select_all}</p>"
        '<ul style="list-style:none;padding:0">'
        + "".join(_item(entry) for entry in items)
        + "</ul>"
        '<p><button type="submit" name="action" value="bin">Move selected to Bin</button> '
        '<button type="submit" name="action" value="keep">Keep all</button></p>'
        "</form>"
    )
    return WebResponse(200, _document("Clean-up", content))


def _plural(n: int) -> str:
    return f"{n} email" if n == 1 else f"{n} emails"


def handle_cleanup_request(
    method: str,
    query: Mapping[str, str],
    form: Mapping[str, list[str]],
    now: datetime,
    secret: str,
    graph,
) -> WebResponse:
    if method == "GET":
        thread_id = verify(query, now, secret)
        if thread_id is None:
            return _message(403, INVALID)
        items = pending_items(graph, thread_id)
        if items is None:
            return _message(410, NOTHING_WAITING)
        return _list_page(items, query)

    if method == "POST":
        link = {key: form[key][0] for key in LINK_FIELDS if form.get(key)}
        thread_id = verify(link, now, secret)
        if thread_id is None:
            return _message(403, INVALID)
        action = (form.get("action") or [""])[0]
        if action not in ("bin", "keep"):
            return _message(400, "Unknown choice. Nothing was changed.")
        ticked = list(form.get("id", [])) if action == "bin" else []
        outcome = resume_approval(graph, thread_id, ticked)
        if outcome.status == "not_found":
            return _message(410, NOTHING_WAITING)
        if outcome.status == "kept":
            return _message(200, "Kept all. Nothing was moved.")
        text = (
            f"Moved {_plural(len(outcome.binned))} to the Bin. "
            "Gmail keeps them there for 30 days if you change your mind."
        )
        if outcome.failed:
            text += f" {_plural(len(outcome.failed))} could not be moved and stayed where they were."
        return _message(200, text)

    return _message(405, "Not allowed.")
