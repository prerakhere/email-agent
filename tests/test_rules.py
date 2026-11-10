from agent.rules import labels_to_categories, learn_rules, load_rules, save_rules
from agent.schemas import Category

# A person's folders that teach a category (what a profile's learn_from_folders holds).
FOLDERS = {
    "Newsletters": Category.NEWSLETTERS,
    "Read Later": Category.NEWSLETTERS,
    "Money/Statements, Receipts": Category.BILLS,
    "Money/Statements, Receipts/Donations": Category.RECEIPTS,
    "Money/subscriptions": Category.BILLS,
}


def categories(labels):
    return labels_to_categories(labels, FOLDERS)


def samples(sender: str, category: Category, n: int) -> list[tuple[str, Category]]:
    return [(sender, category)] * n


def test_consistent_sender_becomes_an_address_rule():
    rules = learn_rules(samples("alerts@examplebank.net", Category.BILLS, 3))
    assert rules == {"alerts@examplebank.net": Category.BILLS}


def test_sender_with_too_few_messages_is_not_learned():
    assert learn_rules(samples("alerts@examplebank.net", Category.BILLS, 1)) == {}


def test_minimum_message_count_is_configurable():
    rules = learn_rules(samples("a@b.com", Category.BILLS, 1), min_messages=1)
    assert rules == {"a@b.com": Category.BILLS}


def test_mixed_categories_below_90_percent_agreement_are_not_learned():
    data = samples("a@b.com", Category.BILLS, 2) + samples(
        "a@b.com", Category.NEWSLETTERS, 2
    )
    assert learn_rules(data) == {}


def test_exactly_90_percent_agreement_is_kept_with_the_majority_category():
    data = samples("a@b.com", Category.BILLS, 9) + samples(
        "a@b.com", Category.NEWSLETTERS, 1
    )
    assert learn_rules(data) == {"a@b.com": Category.BILLS}


def test_sender_names_and_case_are_normalised_before_counting():
    data = [
        ("Shop <DEALS@Shop.com>", Category.NEWSLETTERS),
        ("deals@shop.com", Category.NEWSLETTERS),
    ]
    assert learn_rules(data) == {"deals@shop.com": Category.NEWSLETTERS}


def test_never_learns_important_or_needs_review():
    data = samples("boss@work.com", Category.IMPORTANT, 5) + samples(
        "x@y.com", Category.NEEDS_REVIEW, 5
    )
    assert learn_rules(data) == {}


def test_samples_without_a_parseable_address_are_ignored():
    assert learn_rules(samples("undisclosed-recipients", Category.BILLS, 5)) == {}


def test_domain_rule_created_for_newsletters_with_two_agreeing_addresses():
    data = samples("a@news.example.com", Category.NEWSLETTERS, 2) + samples(
        "b@news.example.com", Category.NEWSLETTERS, 2
    )
    rules = learn_rules(data)
    assert rules["news.example.com"] == Category.NEWSLETTERS
    assert rules["a@news.example.com"] == Category.NEWSLETTERS


def test_no_domain_rule_for_bills_even_with_two_agreeing_addresses():
    # A bank's OTP/alert mail shares the domain; only per-address rules are safe for bills.
    data = samples("a@bank.com", Category.BILLS, 2) + samples(
        "b@bank.com", Category.BILLS, 2
    )
    rules = learn_rules(data)
    assert "bank.com" not in rules
    assert rules["a@bank.com"] == Category.BILLS


def test_no_domain_rule_for_shared_mail_providers():
    data = samples("a@gmail.com", Category.NEWSLETTERS, 2) + samples(
        "b@gmail.com", Category.NEWSLETTERS, 2
    )
    assert "gmail.com" not in learn_rules(data)


def test_no_domain_rule_when_the_domain_also_has_non_newsletter_samples():
    data = (
        samples("a@mixed.com", Category.NEWSLETTERS, 2)
        + samples("b@mixed.com", Category.NEWSLETTERS, 2)
        + samples("c@mixed.com", Category.BILLS, 1)
    )
    assert "mixed.com" not in learn_rules(data)


def test_no_domain_rule_from_a_single_address():
    rules = learn_rules(samples("a@solo.com", Category.NEWSLETTERS, 5))
    assert "solo.com" not in rules
    assert rules["a@solo.com"] == Category.NEWSLETTERS


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "rules.json"
    rules = {"a@b.com": Category.BILLS, "news.com": Category.NEWSLETTERS}
    save_rules(rules, path)
    assert load_rules(path) == rules


def test_load_rules_returns_empty_dict_when_file_is_missing(tmp_path):
    assert load_rules(tmp_path / "nope.json") == {}


# ---- which of the user's folders teach us which category ----


def test_mapped_folders_and_their_sublabels_get_a_category():
    result = categories(
        [
            "Newsletters",
            "Read Later",
            "Read Later/weeklytech",
            "Money/Statements, Receipts",
            "Money/Statements, Receipts/cards/credit cards/CC Statements",
            "Money/subscriptions",
        ]
    )
    assert result == {
        "Newsletters": Category.NEWSLETTERS,
        "Read Later": Category.NEWSLETTERS,
        "Read Later/weeklytech": Category.NEWSLETTERS,
        "Money/Statements, Receipts": Category.BILLS,
        "Money/Statements, Receipts/cards/credit cards/CC Statements": Category.BILLS,
        "Money/subscriptions": Category.BILLS,
    }


def test_unmapped_labels_are_left_out():
    labels = [
        "Money",
        "Money/Bank",
        "Money/Tax",
        "Travel Plans",
        "Travel.",
    ]
    assert categories(labels) == {}


def test_lookalike_label_names_do_not_match():
    # "Newsletters-old" is not underneath "Newsletters".
    assert categories(["Newsletters-old", "Read Later2"]) == {}


def test_label_matching_ignores_case():
    result = categories(["newsletters", "READ LATER/Medium"])
    assert result == {
        "newsletters": Category.NEWSLETTERS,
        "READ LATER/Medium": Category.NEWSLETTERS,
    }


def test_no_labels_gives_empty_mapping():
    assert categories([]) == {}


def test_most_specific_folder_wins_over_its_parent():
    result = categories(
        [
            "Money/Statements, Receipts",
            "Money/Statements, Receipts/Donations",
            "Money/Statements, Receipts/Donations/2025",
            "Money/Statements, Receipts/AWS Bills",
            "Money/Statements, Receipts/Loan, EMI",
        ]
    )
    assert result == {
        "Money/Statements, Receipts": Category.BILLS,
        "Money/Statements, Receipts/Donations": Category.RECEIPTS,
        "Money/Statements, Receipts/Donations/2025": Category.RECEIPTS,
        "Money/Statements, Receipts/AWS Bills": Category.BILLS,
        "Money/Statements, Receipts/Loan, EMI": Category.BILLS,
    }


def test_with_no_folders_configured_no_label_teaches_anything():
    assert labels_to_categories(["Newsletters", "Money/Statements, Receipts"], {}) == {}
