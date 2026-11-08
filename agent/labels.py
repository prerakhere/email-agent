"""Map a Category to the Gmail label to apply (hybrid strategy).

Prefer one of the user's EXISTING labels when there is a clear match; otherwise fall back
to an `Agent/...` label (created on demand by the apply step). Pure logic, no network.
"""

from collections.abc import Collection, Iterable

from agent.rules import labels_to_categories
from agent.schemas import Category

# Existing labels worth filing into, in order of preference. Categories absent here
# (or whose labels don't exist) use the Agent/ fallback.
PREFERRED_EXISTING: dict[Category, tuple[str, ...]] = {
    Category.BILLS: ("Finances/Statements, Receipts",),
    Category.RECEIPTS: ("Finances/Statements, Receipts",),
    Category.NEWSLETTERS: ("Newsletters",),
}

AGENT_FALLBACK: dict[Category, str] = {
    Category.BILLS: "Agent/Bills",
    Category.RECEIPTS: "Agent/Receipts",
    Category.TRANSACTIONS: "Agent/Transactions",
    Category.NEWSLETTERS: "Agent/Newsletters",
    Category.PROMOTIONS: "Agent/Promotions",
    Category.IMPORTANT: "Agent/Important",
    Category.NOTIFICATIONS: "Agent/Notifications",
    Category.JOB_ALERTS: "Agent/Job-Alerts",
    Category.NEEDS_REVIEW: "Agent/Needs-Review",
}


def resolve_label(category: Category, existing_labels: Collection[str]) -> str:
    """Return the label name to apply for `category`.

    Gmail label names are case-insensitive, so match that way and return the real spelling.
    """
    by_lower = {name.lower(): name for name in existing_labels}
    for preferred in PREFERRED_EXISTING.get(category, ()):
        if preferred.lower() in by_lower:
            return by_lower[preferred.lower()]
    return AGENT_FALLBACK[category]


def category_for_labels(label_names: Iterable[str]) -> Category | None:
    """Read a category back from the labels a message already carries (the reverse of
    resolve_label), so already-filed mail needs no model call. None when no label says.

    An Agent/* label wins: it records what the agent itself decided. Otherwise the user's own
    folders count (Newsletters -> newsletters, ...), the most specific folder first.
    """
    names = list(label_names)
    by_agent_label = {name.lower(): cat for cat, name in AGENT_FALLBACK.items()}
    for name in names:
        if name.lower() in by_agent_label:
            return by_agent_label[name.lower()]
    folders = labels_to_categories(names)
    if not folders:
        return None
    return folders[max(folders, key=len)]
