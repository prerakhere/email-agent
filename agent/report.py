"""Plain-text table of proposals for the dry-run (no email bodies, only sender/subject)."""

from collections import Counter

from agent.schemas import Proposal

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
