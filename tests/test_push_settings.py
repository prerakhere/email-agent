import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "push_settings.sh"
TEXT = SCRIPT.read_text()
CODE = "\n".join(line for line in TEXT.splitlines() if not line.strip().startswith("#"))


def test_the_script_is_valid_bash():
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)], check=False, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_it_stops_on_the_first_error_and_never_traces_commands():
    assert "set -euo pipefail" in CODE
    assert (
        "set -x" not in CODE and "xtrace" not in CODE
    )  # tracing would print secret values


def test_the_two_secrets_go_to_key_vault_and_the_app_only_gets_references():
    assert "google-token-json" in CODE and "azure-openai-api-key" in CODE
    assert CODE.count("@Microsoft.KeyVault(VaultName=") == 2
    # the secret values themselves are never placed in an app setting
    assert "GOOGLE_TOKEN_JSON=$(" not in CODE and "GOOGLE_TOKEN_JSON=$token" not in CODE
    assert "AZURE_OPENAI_API_KEY=$(" not in CODE


def test_a_real_run_cannot_start_by_accident():
    assert '"DRY_RUN=true"' in CODE
    assert '"KEEP_IN_INBOX=true"' in CODE
    assert "DRY_RUN=false" not in CODE


def test_it_never_prints_secret_values():
    for line in CODE.splitlines():
        if line.strip().startswith(("echo", "printf")):
            if (
                '> "$secret_file"' in line
            ):  # writing the secret into the private temp file
                continue
            assert "read_env" not in line and "token.json" not in line, line
            assert "$(cat" not in line, line


def test_the_secret_temp_file_is_private_and_removed():
    assert (
        "mktemp" in CODE and "chmod 600" in CODE and "trap" in CODE and "rm -f" in CODE
    )


def test_it_targets_the_resources_created_for_this_project():
    for name in ("gmail-agent-rg", "gmail-agent-func-pj01", "gmail-agent-kv-pj01"):
        assert name in CODE


def test_the_key_is_stored_without_a_trailing_newline():
    # A trailing newline once made the stored key an illegal HTTP header value.
    assert 'printf \'%s\' "$(read_env AZURE_OPENAI_API_KEY)" > "$secret_file"' in CODE
    assert 'read_env AZURE_OPENAI_API_KEY > "$secret_file"' not in CODE
