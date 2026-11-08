import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "deploy.sh"
TEXT = SCRIPT.read_text()
CODE = "\n".join(line for line in TEXT.splitlines() if not line.strip().startswith("#"))


def test_the_script_is_valid_bash():
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)], check=False, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_it_stops_on_the_first_error_and_never_traces_commands():
    assert "set -euo pipefail" in CODE
    assert "set -x" not in CODE


def test_it_checks_lint_and_tests_before_publishing():
    assert (
        CODE.index("ruff check")
        < CODE.index("pytest")
        < CODE.index("functionapp publish")
    )


def test_requirements_come_from_the_lockfile_without_dev_tools():
    assert "uv export" in CODE and "--no-dev" in CODE and "--no-emit-project" in CODE


def test_it_publishes_to_this_projects_function_app_only():
    assert "gmail-agent-func-pj01" in CODE


def test_it_never_uploads_local_settings():
    assert "publish-local-settings" not in CODE
    assert "--publish-settings-only" not in CODE


def test_the_generated_requirements_file_is_gitignored_but_not_excluded_from_the_upload():
    assert "requirements.txt" in (ROOT / ".gitignore").read_text().splitlines()
    funcignore = (ROOT / ".funcignore").read_text().splitlines()
    assert "requirements.txt" not in funcignore
