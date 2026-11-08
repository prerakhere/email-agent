import pytest

from agent.labels import AGENT_FALLBACK, category_for_labels, resolve_label
from agent.schemas import Category

# Subset of the real label tree (see scripts/list_labels.py).
REAL_LABELS = {
    "Finances",
    "Finances/Statements, Receipts",
    "Finances/subscriptions",
    "Newsletters",
    "Job Applications",
    "To Go Through",
    "To Go Through/bytebytego",
}


def test_bills_go_to_existing_statements_label():
    assert resolve_label(Category.BILLS, REAL_LABELS) == "Finances/Statements, Receipts"


def test_receipts_go_to_existing_statements_label():
    assert (
        resolve_label(Category.RECEIPTS, REAL_LABELS) == "Finances/Statements, Receipts"
    )


def test_newsletters_go_to_existing_newsletters_label():
    assert resolve_label(Category.NEWSLETTERS, REAL_LABELS) == "Newsletters"


def test_job_alerts_never_go_into_job_applications():
    # "Job Applications" is for applications you made, not recruiter/alert mail.
    assert resolve_label(Category.JOB_ALERTS, REAL_LABELS) == "Agent/Job-Alerts"


def test_needs_review_always_uses_agent_label():
    assert resolve_label(Category.NEEDS_REVIEW, REAL_LABELS) == "Agent/Needs-Review"


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        (Category.BILLS, "Agent/Bills"),
        (Category.RECEIPTS, "Agent/Receipts"),
        (Category.NEWSLETTERS, "Agent/Newsletters"),
    ],
)
def test_falls_back_to_agent_label_when_preferred_is_missing(category, expected):
    assert resolve_label(category, set()) == expected


def test_categories_with_no_existing_home_use_agent_labels():
    assert resolve_label(Category.PROMOTIONS, REAL_LABELS) == "Agent/Promotions"
    assert resolve_label(Category.NOTIFICATIONS, REAL_LABELS) == "Agent/Notifications"
    assert resolve_label(Category.IMPORTANT, REAL_LABELS) == "Agent/Important"


def test_match_is_case_insensitive_and_returns_the_real_spelling():
    assert resolve_label(Category.NEWSLETTERS, {"newsletters"}) == "newsletters"


@pytest.mark.parametrize("category", list(Category))
def test_every_category_resolves_to_a_label(category):
    assert resolve_label(category, REAL_LABELS)


@pytest.mark.parametrize("category", list(Category))
def test_every_agent_label_maps_back_to_its_category(category):
    assert category_for_labels([AGENT_FALLBACK[category]]) == category


def test_the_users_own_folders_map_to_a_category():
    assert category_for_labels(["Newsletters"]) == Category.NEWSLETTERS
    assert category_for_labels(["To Go Through/bytebytego"]) == Category.NEWSLETTERS
    assert category_for_labels(["Finances/Statements, Receipts"]) == Category.BILLS
    donations = ["Finances/Statements, Receipts/Donations"]
    assert (
        category_for_labels(donations) == Category.RECEIPTS
    )  # most specific folder wins


def test_matching_ignores_case():
    assert category_for_labels(["agent/job-alerts"]) == Category.JOB_ALERTS


def test_an_agent_label_wins_over_one_of_the_users_folders():
    labels = ["Newsletters", "Agent/Promotions"]
    assert category_for_labels(labels) == Category.PROMOTIONS


def test_labels_that_say_nothing_about_a_category_give_none():
    assert category_for_labels(["Job Applications", "Random"]) is None
    assert category_for_labels([]) is None


def test_transactions_get_their_own_agent_label():
    assert resolve_label(Category.TRANSACTIONS, REAL_LABELS) == "Agent/Transactions"
    assert category_for_labels(["Agent/Transactions"]) == Category.TRANSACTIONS


def test_agent_labels_can_be_ignored_while_the_users_own_folders_still_count():
    assert category_for_labels(["Agent/Promotions"], trust_agent_labels=False) is None
    assert (
        category_for_labels(["Newsletters"], trust_agent_labels=False)
        == Category.NEWSLETTERS
    )
    both = ["Newsletters", "Agent/Promotions"]
    assert category_for_labels(both, trust_agent_labels=False) == Category.NEWSLETTERS
    assert (
        category_for_labels(both) == Category.PROMOTIONS
    )  # trusted by default: unchanged
