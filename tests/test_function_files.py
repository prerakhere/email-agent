import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOST = json.loads((ROOT / "host.json").read_text())
FUNCIGNORE = {
    line.strip()
    for line in (ROOT / ".funcignore").read_text().splitlines()
    if line.strip() and not line.startswith("#")
}
EXAMPLE = json.loads((ROOT / "local.settings.json.example").read_text())


def test_libraries_log_at_warning_so_no_email_text_can_leak_but_our_own_logs_show():
    levels = HOST["logging"]["logLevel"]
    assert levels["default"] == "Warning"
    assert levels["gmail_agent"] == "Information"


def test_secrets_and_personal_files_are_never_uploaded_with_the_app():
    must_exclude = {
        ".env",
        "token*.json",
        "credentials*.json",
        "local.settings.json",
        "digest_preview.html",
        "WORKLOG.md",
        "LEARNING.md",
        ".git",
        ".venv",
        "tests",
        "scripts",
    }
    assert must_exclude <= FUNCIGNORE


def test_the_files_the_app_reads_at_run_time_are_still_uploaded():
    assert "rules.json" not in FUNCIGNORE and "digest.toml" not in FUNCIGNORE
    assert "agent" not in FUNCIGNORE and "function_app.py" not in FUNCIGNORE


def test_the_example_settings_list_every_setting_the_job_reads_and_holds_no_secrets():
    values = EXAMPLE["Values"]
    needed = {
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_API_VERSION",
        "AZURE_OPENAI_DEPLOYMENT",
        "GOOGLE_TOKEN_JSON",
        "SHEET_ID",
        "DRY_RUN",
        "KEEP_IN_INBOX",
        "DIGEST_HOURS",
        "FUNCTIONS_WORKER_RUNTIME",
    }
    assert needed <= set(values)
    assert values["DRY_RUN"] == "true"  # the safe default
    assert all(
        v.startswith("<") or v in {"true", "24", "python", "UseDevelopmentStorage=true"}
        for k, v in values.items()
        if k != "AzureWebJobsStorage"
    )


def test_the_real_local_settings_file_is_gitignored():
    assert "local.settings.json" in (ROOT / ".gitignore").read_text().splitlines()


def test_the_optional_personal_files_are_uploaded_with_the_app():
    # rules.json, digest.toml and profile.toml are read at run time from the app folder.
    for name in ("rules.json", "digest.toml", "profile.toml"):
        assert name not in FUNCIGNORE, name
