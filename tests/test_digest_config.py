import pytest

from agent.digest_config import (
    DEFAULT_CONFIG,
    DigestConfig,
    DigestSection,
    load_digest_config,
)
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
        "Bills and receipts",
        "Job alerts",
        "Newsletters",
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
    assert DEFAULT_CONFIG.section_for(Category.BILLS).title == "Bills and receipts"
    assert DEFAULT_CONFIG.section_for(Category.RECEIPTS).title == "Bills and receipts"


def test_categories_in_no_section_have_no_section():
    assert DEFAULT_CONFIG.section_for(Category.PROMOTIONS) is None
    assert DEFAULT_CONFIG.section_for(Category.NOTIFICATIONS) is None


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
