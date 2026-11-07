"""Plain-text reports for the dry-run.

format_table shows only sender/subject/category. format_sent_preview prints the REDACTED
text that would be sent to the LLM (never the original body), so it can be inspected first.
"""

from collections import Counter
from collections.abc import Mapping

from agent.apply import ApplyResult
from agent.nodes.classify import build_inputs
from agent.nodes.prefilter import prefilter
from agent.schemas import Bill, Category, Email, Proposal
from agent.sheets_client import build_row

# (header, width, getter)
COLUMNS = [
    ("Sender", 30, lambda p: p.sender),
    ("Subject", 36, lambda p: p.subject),
    ("Category", 13, lambda p: p.category.value),
    ("Label", 28, lambda p: p.label),
    ("Conf", 4, lambda p: f"{p.confidence:.2f}"),
    ("By", 4, lambda p: p.source),
]


def _fit(text: str, width: int) -> str:
    text = " ".join(text.split())  # no newlines inside a table cell
    if len(text) > width:
        text = text[: width - 1] + "…"
    return text.ljust(width)


def format_table(proposals: list[Proposal]) -> str:
    if not proposals:
        return "No emails to show."
    header = "  ".join(name.ljust(width) for name, width, _ in COLUMNS)
    lines = [header, "-" * len(header)]
    for p in proposals:
        lines.append(
            "  ".join(_fit(get(p), width) for _, width, get in COLUMNS).rstrip()
        )
    by_category = Counter(p.category.value for p in proposals)
    rules = sum(1 for p in proposals if p.source == "rule")
    counts = ", ".join(f"{name}={n}" for name, n in sorted(by_category.items()))
    lines.append(f"\n{len(proposals)} emails, {rules} decided by rules | {counts}")
    return "\n".join(lines)


def format_sent_preview(emails: list[Email], rules: Mapping[str, Category]) -> str:
    """Show exactly what the LLM would receive. Rule-matched mail is never sent."""
    to_send = [e for e in emails if prefilter(e, rules) is None]
    skipped = len(emails) - len(to_send)
    if not to_send:
        return f"Nothing would be sent to the LLM. {skipped} matched a rule and would not be sent."
    blocks = []
    for n, email in enumerate(to_send, start=1):
        sent = build_inputs(email)
        blocks.append(
            f"--- #{n} ---\n"
            f"From: {sent['sender']}\n"
            f"Subject: {sent['subject']}\n"
            f"Has unsubscribe header: {sent['has_unsubscribe']}\n"
            f"Body start (redacted): {sent['body_preview']}"
        )
    header = (
        f"{len(to_send)} of {len(emails)} emails would be sent to the LLM; "
        f"{skipped} matched a rule and would not be sent. Exact (redacted) content:"
    )
    return header + "\n\n" + "\n\n".join(blocks)


def format_apply_report(result: ApplyResult, dry_run: bool) -> str:
    """What apply would do (dry run) or did: one LABEL/MOVE/KEEP line per email, then a summary."""
    if not result.planned and not result.skipped:
        return "Nothing to move."
    keep = result.keep_in_inbox
    verb = "LABEL" if keep else "MOVE"
    lines = []
    for p in result.planned:
        lines.append(
            f"{verb:<5} {_fit(p.sender, 28)}  {_fit(p.subject, 34)}  -> {p.label}"
        )
    for p, why in result.skipped:
        lines.append(f"KEEP  {_fit(p.sender, 28)}  {_fit(p.subject, 34)}  ({why})")
    if keep:
        tail = "All mail stays in the inbox."
        if dry_run:
            summary = (
                f"DRY RUN: nothing was changed. "
                f"{len(result.planned)} would be labelled. {tail}"
            )
        else:
            summary = f"{len(result.moved)} labelled. {tail}"
    elif dry_run:
        summary = (
            f"DRY RUN: nothing was changed. {len(result.planned)} would move, "
            f"{len(result.skipped)} would stay in the inbox."
        )
    else:
        summary = f"{len(result.moved)} moved, {len(result.skipped)} left in the inbox."
    return "\n".join(lines) + "\n\n" + summary


def format_bill_plan(items: list[tuple[Email, Category, Bill]], missed: int = 0) -> str:
    """The sheet rows a run would add (built by the same code that writes them)."""
    note = ""
    if missed:
        noun = "mail" if missed == 1 else "mails"
        note = f"{missed} bill/receipt {noun} had no readable amount and would not be logged."
    if not items:
        return "\n".join(x for x in ("No bills or receipts to log.", note) if x)
    lines = []
    for email, category, bill in items:
        row = build_row(email, category, bill)
        due = row[5] or "-"
        lines.append(
            f"LOG   {row[1]:<7} {_fit(row[2], 24)}  {row[3]:>12,.2f} {row[4]}  due {due:<10}  {row[6]}"
        )
    noun = "row" if len(items) == 1 else "rows"
    lines.append(
        f"\nDRY RUN: nothing was written. {len(items)} {noun} would be added to the sheet."
    )
    if note:
        lines.append(note)
    return "\n".join(lines)
