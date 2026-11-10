import json
from unittest.mock import MagicMock

import pytest

from agent import runtime
from agent.digest_config import DEFAULT_CONFIG
from agent.profile import Profile
from agent.runtime import build_dependencies
from agent.schemas import Category

ENV = {
    "AZURE_OPENAI_ENDPOINT": "https://example.cognitiveservices.azure.com/",
    "AZURE_OPENAI_API_KEY": "not-a-real-key",
    "AZURE_OPENAI_API_VERSION": "2025-01-01-preview",
    "AZURE_OPENAI_DEPLOYMENT": "gpt-4.1-mini",
    "GOOGLE_TOKEN_JSON": "{}",
    "SHEET_ID": "sheet-123",
}


@pytest.fixture
def google(monkeypatch):
    """Stand-ins for the network: fake credentials and a recording Google client builder."""
    built = []

    def fake_build(api, version, **kwargs):
        built.append((api, version, kwargs))
        return MagicMock(name=api)

    monkeypatch.setattr(runtime, "refreshed_credentials", lambda env: "creds")
    monkeypatch.setattr(runtime, "build", fake_build)
    return built


def test_gmail_and_sheets_clients_are_built_with_the_refreshed_credentials(
    google, tmp_path
):
    deps = build_dependencies(ENV, root=tmp_path)
    assert [(api, version) for api, version, _ in google] == [
        ("gmail", "v1"),
        ("sheets", "v4"),
    ]
    for _, _, kwargs in google:
        assert kwargs["credentials"] == "creds"
        assert kwargs["cache_discovery"] is False  # no file cache in a serverless host
    assert deps.gmail is not None and deps.sheets is not None


def test_the_transaction_extractor_is_built_too(google, tmp_path):
    assert build_dependencies(ENV, root=tmp_path).transaction_extractor is not None


def test_without_a_sheet_id_there_is_no_sheets_client(google, tmp_path):
    env = {k: v for k, v in ENV.items() if k != "SHEET_ID"}
    deps = build_dependencies(env, root=tmp_path)
    assert deps.sheets is None
    assert [api for api, _, _ in google] == ["gmail"]


def test_learned_rules_are_read_from_the_app_folder(google, tmp_path):
    (tmp_path / "rules.json").write_text(json.dumps({"jobsite.example": "job_alerts"}))
    deps = build_dependencies(ENV, root=tmp_path)
    assert deps.rules == {"jobsite.example": Category.JOB_ALERTS}


def test_missing_rules_and_digest_files_mean_no_rules_and_the_default_digest(
    google, tmp_path
):
    deps = build_dependencies(ENV, root=tmp_path)
    assert deps.rules == {} and deps.config == DEFAULT_CONFIG


def test_a_digest_toml_in_the_app_folder_is_used(google, tmp_path):
    (tmp_path / "digest.toml").write_text(
        '[[sections]]\ntitle = "Only"\ncategories = ["important"]\nstyle = "s"\n'
    )
    deps = build_dependencies(ENV, root=tmp_path)
    assert [s.title for s in deps.config.sections] == ["Only"]


def test_a_profile_toml_in_the_app_folder_is_used(google, tmp_path):
    (tmp_path / "profile.toml").write_text(
        'timezone = "Asia/Kolkata"\n[learn_from_folders]\n"Reading list" = "newsletters"\n'
    )
    deps = build_dependencies(ENV, root=tmp_path)
    assert deps.profile.timezone == "Asia/Kolkata"
    assert deps.profile.learn_from_folders == {"Reading list": Category.NEWSLETTERS}


def test_without_a_profile_file_the_neutral_profile_is_used(google, tmp_path):
    assert build_dependencies(ENV, root=tmp_path).profile == Profile()


def test_a_missing_azure_setting_fails_fast_before_any_google_call(
    monkeypatch, tmp_path
):
    def boom(env):
        raise AssertionError("must not reach Google")

    monkeypatch.setattr(runtime, "refreshed_credentials", boom)
    env = {k: v for k, v in ENV.items() if k != "AZURE_OPENAI_API_KEY"}
    with pytest.raises(ValueError, match="AZURE_OPENAI_API_KEY"):
        build_dependencies(env, root=tmp_path)
