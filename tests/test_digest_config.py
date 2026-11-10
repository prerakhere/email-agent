import pytest

from agent.digest_config import (
    DEFAULT_CONFIG,
    DigestConfig,
    DigestSection,
    load_digest_config,
)
from agent.gmail_client import BODY_PREVIEW_CHARS
from agent.schemas import Category


def section(**kwargs) -> dict:
    defaults = {
        "title": "Bills",
        "categories": ["bills"],
        "style": "Amount and due date.",
    }
    return {**defaults, **kwargs}


def test_the_defaults_cover_the_sections_the_digest_needs_in_order():
    titles = [s.title for s in DEFAULT_CONFIG.sections]
    assert titles == [
        "Important",
        "Bills and payments",
        "Job alerts",
        "Newsletters",
        "Promotions",
        "Notifications",
        "Needs review",
    ]
    assert all(s.style.strip() for s in DEFAULT_CONFIG.sections)


def test_default_important_section_asks_for_action_points():
    important = DEFAULT_CONFIG.section_for(Category.IMPORTANT)
    assert important is not None and "action" in important.style.lower()


def test_default_job_alerts_are_summarised_as_a_group_not_one_by_one():
    alerts = DEFAULT_CONFIG.section_for(Category.JOB_ALERTS)
    assert alerts is not None and alerts.mode == "group"


def test_section_for_finds_the_section_that_owns_a_category():
    assert DEFAULT_CONFIG.section_for(Category.BILLS).title == "Bills and payments"
    assert DEFAULT_CONFIG.section_for(Category.RECEIPTS).title == "Bills and payments"


def test_every_category_has_a_section_in_the_defaults():
    for category in Category:
        assert DEFAULT_CONFIG.section_for(category) is not None, category


def test_promotions_and_notifications_get_short_group_summaries_by_default():
    for category in (Category.PROMOTIONS, Category.NOTIFICATIONS):
        found = DEFAULT_CONFIG.section_for(category)
        assert found.mode == "group"
        assert "short" in found.style.lower() or "brief" in found.style.lower()


def test_categories_in_no_section_have_no_section():
    config = DigestConfig(sections=[DigestSection(**section())])
    assert config.section_for(Category.PROMOTIONS) is None


def test_a_category_in_two_sections_is_rejected():
    with pytest.raises(ValueError, match="more than one section"):
        DigestConfig(
            sections=[
                DigestSection(**section(title="A", categories=["bills"])),
                DigestSection(**section(title="B", categories=["bills", "receipts"])),
            ]
        )


def test_a_config_needs_at_least_one_section():
    with pytest.raises(ValueError):
        DigestConfig(sections=[])


@pytest.mark.parametrize(
    "bad",
    [
        {"title": ""},
        {"categories": []},
        {"max_items": 0},
        {"mode": "everything"},
        {"categories": ["not_a_category"]},
    ],
)
def test_invalid_section_values_are_rejected(bad):
    with pytest.raises(ValueError):
        DigestSection(**section(**bad))


def test_a_missing_file_gives_the_defaults(tmp_path):
    assert load_digest_config(tmp_path / "digest.toml") == DEFAULT_CONFIG


def test_a_toml_file_is_loaded_with_defaults_for_the_optional_fields(tmp_path):
    path = tmp_path / "digest.toml"
    path.write_text(
        """
# my digest
[[sections]]
title = "Work"
categories = ["important", "job_alerts"]
style = "List action points."

[[sections]]
title = "Reading"
categories = ["newsletters"]
style = "Two key points each."
mode = "group"
max_items = 3
"""
    )
    config = load_digest_config(path)
    assert [s.title for s in config.sections] == ["Work", "Reading"]
    work, reading = config.sections
    assert work.categories == [Category.IMPORTANT, Category.JOB_ALERTS]
    assert work.mode == "per_email" and work.max_items == 10
    assert reading.mode == "group" and reading.max_items == 3


def test_an_unknown_category_in_the_file_is_named_in_the_error(tmp_path):
    path = tmp_path / "digest.toml"
    path.write_text('[[sections]]\ntitle = "X"\ncategories = ["jobz"]\nstyle = "s"\n')
    with pytest.raises(ValueError, match="jobz"):
        load_digest_config(path)


def test_a_file_that_is_not_valid_toml_gives_a_clear_error(tmp_path):
    path = tmp_path / "digest.toml"
    path.write_text("this is = = not toml [[")
    with pytest.raises(ValueError, match="not valid TOML"):
        load_digest_config(path)


def test_body_size_defaults_to_1500_and_newsletters_get_more():
    assert DigestSection(**section()).body_chars == 1500
    assert DEFAULT_CONFIG.section_for(Category.NEWSLETTERS).body_chars == 3000
    assert DEFAULT_CONFIG.section_for(Category.IMPORTANT).body_chars == 1500


def test_no_section_asks_for_more_text_than_the_fetch_keeps():
    assert BODY_PREVIEW_CHARS == 3000
    assert all(s.body_chars <= BODY_PREVIEW_CHARS for s in DEFAULT_CONFIG.sections)


@pytest.mark.parametrize("bad", [0, 199, BODY_PREVIEW_CHARS + 1])
def test_a_silly_body_size_is_rejected(bad):
    with pytest.raises(ValueError):
        DigestSection(**section(body_chars=bad))


def test_body_size_can_be_set_in_the_toml_file(tmp_path):
    path = tmp_path / "digest.toml"
    path.write_text(
        '[[sections]]\ntitle = "Reading"\ncategories = ["newsletters"]\nbody_chars = 2500\n'
    )
    assert load_digest_config(path).sections[0].body_chars == 2500


def test_money_mail_is_one_table_by_default():
    money = DEFAULT_CONFIG.section_for(Category.BILLS)
    assert (money.mode, money.table) == ("table", "money")
    assert money.max_items >= 20  # a busy day has many small payments


def test_transactions_live_inside_the_money_section():
    section = DEFAULT_CONFIG.section_for(Category.TRANSACTIONS)
    assert section is not None and section.title == "Bills and payments"


def test_every_default_section_asks_for_a_single_line():
    # The digest is a next-day review: one line at most per item.
    for section in DEFAULT_CONFIG.sections:
        assert "line" in section.style.lower(), section.title
        assert "two sentences" not in section.style.lower(), section.title


# ---- table sections: bills and transactions shown as a table, not one summary per mail ----


def test_a_table_section_must_say_which_table_it_shows():
    with pytest.raises(ValueError, match="table"):
        DigestSection(**section(mode="table"))
    ok = DigestSection(**section(mode="table", table="bills"))
    assert ok.mode == "table" and ok.table == "bills"


def test_only_known_tables_are_allowed():
    with pytest.raises(ValueError):
        DigestSection(**section(mode="table", table="weather"))


def test_a_table_name_without_table_mode_is_rejected():
    with pytest.raises(ValueError, match="table"):
        DigestSection(**section(mode="per_email", table="bills"))


def test_a_table_section_can_be_set_in_the_toml_file(tmp_path):
    path = tmp_path / "digest.toml"
    path.write_text(
        '[[sections]]\ntitle = "Spend"\ncategories = ["transactions"]\n'
        'mode = "table"\ntable = "transactions"\nmax_items = 30\n'
    )
    spend = load_digest_config(path).sections[0]
    assert (
        spend.mode == "table"
        and spend.table == "transactions"
        and spend.max_items == 30
    )


def test_the_default_digest_has_one_money_section_for_all_money_mail():
    money = DEFAULT_CONFIG.section_for(Category.BILLS)
    assert (
        money.title == "Bills and payments"
        and money.mode == "table"
        and money.table == "money"
    )
    for category in (
        Category.RECEIPTS,
        Category.TRANSACTIONS,
        Category.STATEMENTS,
    ):
        assert DEFAULT_CONFIG.section_for(category) is money


def test_the_older_separate_bills_and_transactions_tables_still_validate():
    DigestSection(title="B", categories=["bills"], mode="table", table="bills")
    DigestSection(
        title="T", categories=["transactions"], mode="table", table="transactions"
    )
