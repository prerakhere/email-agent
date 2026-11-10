import pytest

from agent.labels import AGENT_FALLBACK, category_for_labels, resolve_label
from agent.schemas import Category

# A person's profile: folders that teach a category, and existing labels to file into.
FOLDERS = {
    "Newsletters": Category.NEWSLETTERS,
    "Read Later": Category.NEWSLETTERS,
    "Money/Statements, Receipts": Category.BILLS,
    "Money/Statements, Receipts/Donations": Category.RECEIPTS,
    "Money/subscriptions": Category.BILLS,
}
FILE_INTO = {
    Category.BILLS: ["Money/Statements, Receipts"],
    Category.RECEIPTS: ["Money/Statements, Receipts"],
    Category.STATEMENTS: ["Money/Statements, Receipts"],
    Category.NEWSLETTERS: ["Newsletters"],
}


def resolve(category, existing):
    return resolve_label(category, existing, FILE_INTO)


def read(names, **kwargs):
    return category_for_labels(names, folders=FOLDERS, **kwargs)


# Subset of the real label tree (see scripts/list_labels.py).
REAL_LABELS = {
    "Money",
    "Money/Statements, Receipts",
    "Money/subscriptions",
    "Newsletters",
    "Travel Plans",
    "Read Later",
    "Read Later/weeklytech",
}


def test_bills_go_to_existing_statements_label():
    assert resolve(Category.BILLS, REAL_LABELS) == "Money/Statements, Receipts"


def test_receipts_go_to_existing_statements_label():
    assert resolve(Category.RECEIPTS, REAL_LABELS) == "Money/Statements, Receipts"


def test_newsletters_go_to_existing_newsletters_label():
    assert resolve(Category.NEWSLETTERS, REAL_LABELS) == "Newsletters"


def test_job_alerts_never_go_into_job_applications():
    # "Travel Plans" is for applications you made, not recruiter/alert mail.
    assert resolve(Category.JOB_ALERTS, REAL_LABELS) == "Agent/Job-Alerts"


def test_needs_review_always_uses_agent_label():
    assert resolve(Category.NEEDS_REVIEW, REAL_LABELS) == "Agent/Needs-Review"


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        (Category.BILLS, "Agent/Bills"),
        (Category.RECEIPTS, "Agent/Receipts"),
        (Category.NEWSLETTERS, "Agent/Newsletters"),
    ],
)
def test_falls_back_to_agent_label_when_preferred_is_missing(category, expected):
    assert resolve(category, set()) == expected


def test_categories_with_no_existing_home_use_agent_labels():
    assert resolve(Category.PROMOTIONS, REAL_LABELS) == "Agent/Promotions"
    assert resolve(Category.NOTIFICATIONS, REAL_LABELS) == "Agent/Notifications"
    assert resolve(Category.IMPORTANT, REAL_LABELS) == "Agent/Important"


def test_match_is_case_insensitive_and_returns_the_real_spelling():
    assert resolve(Category.NEWSLETTERS, {"newsletters"}) == "newsletters"


@pytest.mark.parametrize("category", list(Category))
def test_every_category_resolves_to_a_label(category):
    assert resolve(category, REAL_LABELS)


@pytest.mark.parametrize("category", list(Category))
def test_every_agent_label_maps_back_to_its_category(category):
    assert read([AGENT_FALLBACK[category]]) == category


def test_the_users_own_folders_map_to_a_category():
    assert read(["Newsletters"]) == Category.NEWSLETTERS
    assert read(["Read Later/weeklytech"]) == Category.NEWSLETTERS
    assert read(["Money/Statements, Receipts"]) == Category.BILLS
    donations = ["Money/Statements, Receipts/Donations"]
    assert read(donations) == Category.RECEIPTS  # most specific folder wins


def test_matching_ignores_case():
    assert read(["agent/job-alerts"]) == Category.JOB_ALERTS


def test_an_agent_label_wins_over_one_of_the_users_folders():
    labels = ["Newsletters", "Agent/Promotions"]
    assert read(labels) == Category.PROMOTIONS


def test_labels_that_say_nothing_about_a_category_give_none():
    assert read(["Travel Plans", "Random"]) is None
    assert read([]) is None


def test_transactions_get_their_own_agent_label():
    assert resolve(Category.TRANSACTIONS, REAL_LABELS) == "Agent/Transactions"
    assert read(["Agent/Transactions"]) == Category.TRANSACTIONS


def test_agent_labels_can_be_ignored_while_the_users_own_folders_still_count():
    assert read(["Agent/Promotions"], trust_agent_labels=False) is None
    assert read(["Newsletters"], trust_agent_labels=False) == Category.NEWSLETTERS
    both = ["Newsletters", "Agent/Promotions"]
    assert read(both, trust_agent_labels=False) == Category.NEWSLETTERS
    assert read(both) == Category.PROMOTIONS  # trusted by default: unchanged


# ---- statements: a periodic record with nothing to pay ----


def test_a_statement_goes_to_the_users_statements_folder_when_it_exists():
    from agent.schemas import Category

    existing = ["Money/Statements, Receipts"]
    assert resolve(Category.STATEMENTS, existing) == existing[0]


def test_a_statement_falls_back_to_an_agent_label_and_reads_back_from_it():
    from agent.schemas import Category

    assert resolve(Category.STATEMENTS, []) == "Agent/Statements"
    assert read(["Agent/Statements"]) == Category.STATEMENTS


# ---- neutral without a profile ----


def test_with_no_profile_every_category_uses_its_agent_label():
    real = {"Money/Statements, Receipts", "Newsletters"}
    assert resolve_label(Category.BILLS, real) == "Agent/Bills"
    assert resolve_label(Category.NEWSLETTERS, real) == "Agent/Newsletters"


def test_with_no_profile_a_users_own_folder_says_nothing_about_a_category():
    assert category_for_labels(["Newsletters"]) is None
    assert category_for_labels(["Agent/Newsletters"]) == Category.NEWSLETTERS


def test_a_profiles_first_existing_label_wins_and_a_missing_one_falls_through():
    file_into = {Category.BILLS: ["Money/Bills", "Money"]}
    assert resolve_label(Category.BILLS, {"Money"}, file_into) == "Money"
    assert (
        resolve_label(Category.BILLS, {"Money", "Money/Bills"}, file_into)
        == "Money/Bills"
    )
    assert resolve_label(Category.BILLS, {"Other"}, file_into) == "Agent/Bills"
