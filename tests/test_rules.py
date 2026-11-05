from agent.rules import labels_to_categories, learn_rules, load_rules, save_rules
from agent.schemas import Category


def samples(sender: str, category: Category, n: int) -> list[tuple[str, Category]]:
    return [(sender, category)] * n


def test_consistent_sender_becomes_an_address_rule():
    rules = learn_rules(samples("alerts@hdfcbank.net", Category.BILLS, 3))
    assert rules == {"alerts@hdfcbank.net": Category.BILLS}


def test_sender_with_too_few_messages_is_not_learned():
    assert learn_rules(samples("alerts@hdfcbank.net", Category.BILLS, 1)) == {}


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
    result = labels_to_categories(
        [
            "Newsletters",
            "To Go Through",
            "To Go Through/bytebytego",
            "Finances/Statements, Receipts",
            "Finances/Statements, Receipts/cards/credit cards/CC Statements",
            "Finances/subscriptions",
        ]
    )
    assert result == {
        "Newsletters": Category.NEWSLETTERS,
        "To Go Through": Category.NEWSLETTERS,
        "To Go Through/bytebytego": Category.NEWSLETTERS,
        "Finances/Statements, Receipts": Category.BILLS,
        "Finances/Statements, Receipts/cards/credit cards/CC Statements": Category.BILLS,
        "Finances/subscriptions": Category.BILLS,
    }


def test_unmapped_labels_are_left_out():
    labels = [
        "Finances",
        "Finances/Bank",
        "Finances/Tax",
        "Job Applications",
        "Travel.",
    ]
    assert labels_to_categories(labels) == {}


def test_lookalike_label_names_do_not_match():
    # "Newsletters-old" is not underneath "Newsletters".
    assert labels_to_categories(["Newsletters-old", "To Go Through2"]) == {}


def test_label_matching_ignores_case():
    result = labels_to_categories(["newsletters", "TO GO THROUGH/Medium"])
    assert result == {
        "newsletters": Category.NEWSLETTERS,
        "TO GO THROUGH/Medium": Category.NEWSLETTERS,
    }


def test_no_labels_gives_empty_mapping():
    assert labels_to_categories([]) == {}


def test_most_specific_folder_wins_over_its_parent():
    result = labels_to_categories(
        [
            "Finances/Statements, Receipts",
            "Finances/Statements, Receipts/Donations",
            "Finances/Statements, Receipts/Donations/2025",
            "Finances/Statements, Receipts/AWS Bills",
            "Finances/Statements, Receipts/Loan, EMI",
        ]
    )
    assert result == {
        "Finances/Statements, Receipts": Category.BILLS,
        "Finances/Statements, Receipts/Donations": Category.RECEIPTS,
        "Finances/Statements, Receipts/Donations/2025": Category.RECEIPTS,
        "Finances/Statements, Receipts/AWS Bills": Category.BILLS,
        "Finances/Statements, Receipts/Loan, EMI": Category.BILLS,
    }
