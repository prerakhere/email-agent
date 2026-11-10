"""The profile: one place for a person's taste (folders, time zone, currency, what they care about).

The code's defaults are neutral; a gitignored profile.toml holds the personal part.
"""

from pathlib import Path

import pytest

from agent.profile import Profile, load_profile, parse_profile
from agent.schemas import Category

ROOT = Path(__file__).resolve().parent.parent


def test_the_default_profile_is_neutral():
    profile = Profile()
    assert profile.timezone == "UTC"
    assert profile.learn_from_folders == {} and profile.file_into == {}
    assert profile.preferences == []
    assert (
        profile.currency_symbols["USD"] == "$"
        and profile.currency_symbols["INR"] == "₹"
    )


def test_a_profile_file_sets_every_part():
    profile = parse_profile(
        """
timezone = "Asia/Kolkata"
preferences = ["Order updates are noise to me.", "Greetings are promotions."]

[currency_symbols]
CHF = "Fr"

[learn_from_folders]
"Reading list" = "newsletters"

[file_into]
bills = ["Money/Bills", "Money"]
""",
        "profile.toml",
    )
    assert profile.timezone == "Asia/Kolkata"
    assert profile.preferences == [
        "Order updates are noise to me.",
        "Greetings are promotions.",
    ]
    assert profile.currency_symbols["CHF"] == "Fr"
    assert profile.learn_from_folders == {"Reading list": Category.NEWSLETTERS}
    assert profile.file_into == {Category.BILLS: ["Money/Bills", "Money"]}


def test_a_missing_file_gives_the_neutral_default(tmp_path):
    assert load_profile(tmp_path / "profile.toml") == Profile()


def test_a_file_on_disk_is_read(tmp_path):
    path = tmp_path / "profile.toml"
    path.write_text('timezone = "Europe/Paris"\n')
    assert load_profile(path).timezone == "Europe/Paris"


def test_text_that_is_not_toml_is_refused_and_names_its_source():
    with pytest.raises(ValueError, match=r"profile.toml.*TOML"):
        parse_profile("this is = = not toml", "profile.toml")


def test_a_misspelt_key_is_refused_rather_than_silently_ignored():
    with pytest.raises(ValueError, match="timezon"):
        parse_profile('timezon = "UTC"', "profile.toml")


def test_an_unknown_time_zone_is_refused():
    with pytest.raises(ValueError, match="timezone"):
        parse_profile('timezone = "Mars/Olympus"', "profile.toml")


def test_a_folder_mapped_to_an_unknown_category_is_refused():
    with pytest.raises(ValueError, match="category|Category|learn_from_folders"):
        parse_profile('[learn_from_folders]\n"X" = "banana"', "profile.toml")


def test_preferences_are_limited_in_number_and_length_and_cannot_be_empty():
    with pytest.raises(ValueError, match="preferences"):
        parse_profile("preferences = [" + ",".join(['"a"'] * 21) + "]", "profile.toml")
    with pytest.raises(ValueError, match="preferences"):
        parse_profile('preferences = ["' + "x" * 301 + '"]', "profile.toml")
    with pytest.raises(ValueError, match="preferences"):
        parse_profile('preferences = ["   "]', "profile.toml")


def test_currency_symbols_must_be_short_and_keyed_by_a_three_letter_code():
    with pytest.raises(ValueError, match="currency_symbols"):
        parse_profile('[currency_symbols]\nINR = "rupees"', "profile.toml")
    with pytest.raises(ValueError, match="currency_symbols"):
        parse_profile('[currency_symbols]\nrupee = "₹"', "profile.toml")


def test_the_committed_example_profile_is_valid_and_shows_every_setting():
    text = (ROOT / "profile.example.toml").read_text()
    profile = parse_profile(text, "profile.example.toml")
    assert profile.timezone and profile.preferences
    assert profile.learn_from_folders and profile.file_into


def test_a_profiles_currency_symbols_are_added_to_the_defaults_not_replacing_them():
    profile = parse_profile('[currency_symbols]\nCHF = "Fr"', "profile.toml")
    assert profile.currency_symbols["CHF"] == "Fr"
    assert (
        profile.currency_symbols["INR"] == "₹"
        and profile.currency_symbols["USD"] == "$"
    )


def test_a_profile_can_override_a_default_symbol():
    profile = parse_profile('[currency_symbols]\nINR = "Rs"', "profile.toml")
    assert profile.currency_symbols["INR"] == "Rs"


def test_a_missing_profile_file_is_announced_in_the_log(tmp_path, caplog):
    with caplog.at_level("WARNING", logger="gmail_agent.profile"):
        load_profile(tmp_path / "profile.toml")
    assert "profile.toml" in caplog.text and "neutral" in caplog.text


def test_the_agents_own_label_tree_cannot_be_a_teacher():
    for folder in ("Agent", "Agent/Bills", "agent/newsletters"):
        with pytest.raises(ValueError, match="Agent"):
            parse_profile(f'[learn_from_folders]\n"{folder}" = "bills"', "profile.toml")


def test_a_folder_may_be_both_learned_from_and_filed_into():
    # The owner's choice: their folder is treated as their own filing even when the agent put the
    # mail there (so the agent's guesses there are not re-checked). Allowed, documented in the example.
    text = '[learn_from_folders]\n"Money" = "bills"\n[file_into]\nbills = ["Money"]'
    assert parse_profile(text, "profile.toml").file_into[Category.BILLS] == ["Money"]
