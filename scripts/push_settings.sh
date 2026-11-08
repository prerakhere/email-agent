#!/usr/bin/env bash
# Copy this project's secrets and settings to Azure. YOU run it (it reads .env and token.json);
# Claude never sees those files.
#
#   bash scripts/push_settings.sh
#
# - The Google token and the Azure OpenAI key go into Key Vault as secrets.
# - The Function App gets REFERENCES to them (resolved at run time by its managed identity), so the
#   secret values are never stored in the app's own settings.
# - Everything else is a plain setting. DRY_RUN is set to true: the Function only plans until you
#   deliberately change it. Nothing here prints a secret value.
set -euo pipefail
cd "$(dirname "$0")/.."

RG=gmail-agent-rg
APP=gmail-agent-func-pj01
KV=gmail-agent-kv-pj01

# Read KEY=value from .env (strips surrounding quotes). Used only inside $( ) and files, never echoed.
read_env() { grep -E "^$1=" .env | head -1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//'; }

for name in AZURE_OPENAI_ENDPOINT AZURE_OPENAI_API_KEY AZURE_OPENAI_API_VERSION AZURE_OPENAI_DEPLOYMENT SHEET_ID; do
  [ -n "$(read_env "$name")" ] || { echo "Missing $name in .env: nothing was changed."; exit 1; }
done
[ -f token.json ] || { echo "token.json not found: sign in first. Nothing was changed."; exit 1; }

secret_file="$(mktemp)"
chmod 600 "$secret_file"
trap 'rm -f "$secret_file"' EXIT

echo "1/3 Storing the Google token in Key Vault ..."
az keyvault secret set --vault-name "$KV" --name google-token-json --file token.json -o none

echo "2/3 Storing the Azure OpenAI key in Key Vault ..."
read_env AZURE_OPENAI_API_KEY > "$secret_file"
az keyvault secret set --vault-name "$KV" --name azure-openai-api-key --file "$secret_file" -o none

echo "3/3 Setting the Function App's settings (secrets as Key Vault references) ..."
az functionapp config appsettings set -n "$APP" -g "$RG" -o none --settings \
  "GOOGLE_TOKEN_JSON=@Microsoft.KeyVault(VaultName=$KV;SecretName=google-token-json)" \
  "AZURE_OPENAI_API_KEY=@Microsoft.KeyVault(VaultName=$KV;SecretName=azure-openai-api-key)" \
  "AZURE_OPENAI_ENDPOINT=$(read_env AZURE_OPENAI_ENDPOINT)" \
  "AZURE_OPENAI_API_VERSION=$(read_env AZURE_OPENAI_API_VERSION)" \
  "AZURE_OPENAI_DEPLOYMENT=$(read_env AZURE_OPENAI_DEPLOYMENT)" \
  "SHEET_ID=$(read_env SHEET_ID)" \
  "DRY_RUN=true" \
  "KEEP_IN_INBOX=true" \
  "DIGEST_HOURS=24"

echo "Done. The app now plans only (DRY_RUN=true). Names of its settings:"
az functionapp config appsettings list -n "$APP" -g "$RG" --query "[].name" -o tsv
