"""Map a Category to the Gmail label to apply (hybrid strategy).

Prefer one of the user's EXISTING labels when there is a clear match; otherwise fall back
to an `Agent/...` label (created on demand by the apply step). Pure logic, no network.
"""

from collections.abc import Collection, Iterable, Mapping, Sequence

from agent.rules import labels_to_categories
from agent.schemas import Category

AGENT_FALLBACK: dict[Category, str] = {
    Category.BILLS: "Agent/Bills",
    Category.RECEIPTS: "Agent/Receipts",
    Category.TRANSACTIONS: "Agent/Transactions",
    Category.STATEMENTS: "Agent/Statements",
    Category.NEWSLETTERS: "Agent/Newsletters",
    Category.PROMOTIONS: "Agent/Promotions",
    Category.IMPORTANT: "Agent/Important",
    Category.NOTIFICATIONS: "Agent/Notifications",
    Category.JOB_ALERTS: "Agent/Job-Alerts",
    Category.NEEDS_REVIEW: "Agent/Needs-Review",
}


def resolve_label(
    category: Category,
    existing_labels: Collection[str],
    file_into: Mapping[Category, Sequence[str]] | None = None,
) -> str:
    """Return the label name to apply for `category`.

    `file_into` is the profile's map of categories to the user's existing labels, in order of
    preference; without it (or when none of those labels exist) the Agent/... label is used.
    Gmail label names are case-insensitive, so match that way and return the real spelling.
    """
    by_lower = {name.lower(): name for name in existing_labels}
    for preferred in (file_into or {}).get(category, ()):
        if preferred.lower() in by_lower:
            return by_lower[preferred.lower()]
    return AGENT_FALLBACK[category]


def category_for_labels(
    label_names: Iterable[str],
    trust_agent_labels: bool = True,
    folders: Mapping[str, Category] | None = None,
) -> Category | None:
    """Read a category back from the labels a message already carries (the reverse of
    resolve_label), so already-filed mail needs no model call. None when no label says.

    An Agent/* label wins: it records what the agent itself decided. Otherwise the user's own
    folders count (Newsletters -> newsletters, ...), the most specific folder first. With
    `trust_agent_labels=False` the agent's own labels are ignored (they are only its earlier
    guesses, to be re-checked) while the user's own folders, which are ground truth, still count.
    """
    names = list(label_names)
    by_agent_label = {name.lower(): cat for cat, name in AGENT_FALLBACK.items()}
    for name in names if trust_agent_labels else []:
        if name.lower() in by_agent_label:
            return by_agent_label[name.lower()]
    taught = labels_to_categories(names, folders or {})
    if not taught:
        return None
    return taught[max(taught, key=len)]
