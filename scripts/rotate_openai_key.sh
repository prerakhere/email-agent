#!/usr/bin/env bash
# Replace the Azure OpenAI API key everywhere:   bash scripts/rotate_openai_key.sh
# YOU run it; the new key is never printed and never appears on a command line.
#
# 1. Regenerates BOTH keys of the Azure OpenAI resource: the old keys stop working at once, so
#    whichever one was exposed is dead.
# 2. Stores the new key in Key Vault (no trailing newline, which would break the HTTP header).
# 3. Writes it into your local .env.
# 4. Makes the Function App re-read the secret (Key Vault references cache), then restarts it.
set -euo pipefail
cd "$(dirname "$0")/.."

RG=gmail-agent-rg
AI=gmail-agent-resource
KV=gmail-agent-kv-pj01
APP=gmail-agent-func-pj01

secret_file="$(mktemp)"
chmod 600 "$secret_file"
trap 'rm -f "$secret_file"' EXIT

echo "1/5 Regenerating both keys of $AI (the old keys stop working now) ..."
az cognitiveservices account keys regenerate -n "$AI" -g "$RG" --key-name Key1 -o none
az cognitiveservices account keys regenerate -n "$AI" -g "$RG" --key-name Key2 -o none

echo "2/5 Fetching the new key and storing it in Key Vault ..."
az cognitiveservices account keys list -n "$AI" -g "$RG" --query key1 -o tsv | tr -d '\r\n' > "$secret_file"
[ -s "$secret_file" ] || { echo "Could not read the new key. The old keys are already revoked: run this script again."; exit 1; }
az keyvault secret set --vault-name "$KV" --name azure-openai-api-key --file "$secret_file" -o none

echo "3/5 Updating AZURE_OPENAI_API_KEY in .env ..."
python3 - "$secret_file" <<'PY'
import pathlib
import sys

key = pathlib.Path(sys.argv[1]).read_text().strip()
env = pathlib.Path(".env")
lines = env.read_text().splitlines() if env.exists() else []
found = False
for i, line in enumerate(lines):
    if line.startswith("AZURE_OPENAI_API_KEY="):
        lines[i] = "AZURE_OPENAI_API_KEY=" + key
        found = True
if not found:
    lines.append("AZURE_OPENAI_API_KEY=" + key)
env.write_text("\n".join(lines) + "\n")
env.chmod(0o600)
PY

echo "4/5 Making the app re-read the secret ..."
# A Key Vault reference caches its value: without this the app keeps the REVOKED key and every model
# call fails with 401. Re-saving the same reference forces a fresh resolve.
az functionapp config appsettings set -n "$APP" -g "$RG" -o none --settings \
  "AZURE_OPENAI_API_KEY=@Microsoft.KeyVault(VaultName=$KV;SecretName=azure-openai-api-key)"

echo "5/5 Restarting $APP so it picks everything up ..."
az functionapp restart -n "$APP" -g "$RG" -o none

echo "Done. The new key is in Key Vault and .env; the old keys no longer work."
