import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "rotate_openai_key.sh"
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


def test_it_regenerates_both_keys_so_whichever_leaked_stops_working():
    assert "--key-name Key1" in CODE and "--key-name Key2" in CODE
    assert CODE.index("--key-name Key1") < CODE.index("keys list")


def test_the_new_key_is_stored_without_a_newline_in_a_private_temp_file():
    assert "tr -d '\\r\\n'" in CODE
    assert (
        "mktemp" in CODE and "chmod 600" in CODE and "trap" in CODE and "rm -f" in CODE
    )
    assert '--file "$secret_file"' in CODE


def test_the_key_never_appears_on_a_command_line_or_in_output():
    for line in CODE.splitlines():
        if line.strip().startswith(("echo", "printf")):
            assert (
                "key1" not in line and "$new" not in line and "keys list" not in line
            ), line
    assert (
        "--value" not in CODE
    )  # a --value argument would show the secret in the process list


def test_it_updates_the_vault_the_local_env_file_and_restarts_the_app():
    assert "az keyvault secret set" in CODE and "azure-openai-api-key" in CODE
    assert ".env" in CODE and "AZURE_OPENAI_API_KEY=" in CODE
    assert "az functionapp restart" in CODE


def test_it_targets_this_projects_resources_only():
    for name in (
        "gmail-agent-rg",
        "gmail-agent-resource",
        "gmail-agent-kv-pj01",
        "gmail-agent-func-pj01",
    ):
        assert name in CODE


def test_the_app_is_told_to_re_resolve_the_key_so_it_never_keeps_the_revoked_copy():
    # A Key Vault reference caches its value: after a rotation the app kept the OLD key and every
    # model call failed with 401 until the setting was re-saved.
    assert "az functionapp config appsettings set" in CODE
    assert (
        "AZURE_OPENAI_API_KEY=@Microsoft.KeyVault(VaultName=$KV;SecretName=azure-openai-api-key)"
        in CODE
    )
    assert CODE.index("az keyvault secret set") < CODE.index("appsettings set")
