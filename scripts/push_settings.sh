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
#   deliberately change it. CLEANUP_ENABLED is set to false the same way. Nothing here prints a
#   secret value.
# - The clean-up link secret is generated in Key Vault only if it is missing, so re-running this never
#   breaks approval links already sitting in the inbox. MONGODB-URI (the checkpoint database) is
#   created with the DocumentDB cluster, not here; the app only gets a reference to it.
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

echo "1/4 Storing the Google token in Key Vault ..."
az keyvault secret set --vault-name "$KV" --name google-token-json --file token.json -o none

echo "2/4 Storing the Azure OpenAI key in Key Vault ..."
# printf '%s' adds no newline: a trailing newline in the stored key is an illegal HTTP header value.
printf '%s' "$(read_env AZURE_OPENAI_API_KEY)" > "$secret_file"
az keyvault secret set --vault-name "$KV" --name azure-openai-api-key --file "$secret_file" -o none

echo "3/4 Making sure the clean-up link secret exists in Key Vault ..."
if ! az keyvault secret show --vault-name "$KV" --name cleanup-link-secret -o none 2>/dev/null; then
  python3 -c 'import secrets; print(secrets.token_urlsafe(48), end="")' > "$secret_file"
  az keyvault secret set --vault-name "$KV" --name cleanup-link-secret --file "$secret_file" -o none
fi

echo "4/4 Setting the Function App's settings (secrets as Key Vault references) ..."
az functionapp config appsettings set -n "$APP" -g "$RG" -o none --settings \
  "GOOGLE_TOKEN_JSON=@Microsoft.KeyVault(VaultName=$KV;SecretName=google-token-json)" \
  "AZURE_OPENAI_API_KEY=@Microsoft.KeyVault(VaultName=$KV;SecretName=azure-openai-api-key)" \
  "CLEANUP_LINK_SECRET=@Microsoft.KeyVault(VaultName=$KV;SecretName=cleanup-link-secret)" \
  "MONGODB_URI=@Microsoft.KeyVault(VaultName=$KV;SecretName=MONGODB-URI)" \
  "CLEANUP_BASE_URL=https://$APP.azurewebsites.net" \
  "CLEANUP_ENABLED=false" \
  "AZURE_OPENAI_ENDPOINT=$(read_env AZURE_OPENAI_ENDPOINT)" \
  "AZURE_OPENAI_API_VERSION=$(read_env AZURE_OPENAI_API_VERSION)" \
  "AZURE_OPENAI_DEPLOYMENT=$(read_env AZURE_OPENAI_DEPLOYMENT)" \
  "SHEET_ID=$(read_env SHEET_ID)" \
  "DRY_RUN=true" \
  "KEEP_IN_INBOX=true" \
  "DIGEST_HOURS=24"

echo "Done. The app now plans only (DRY_RUN=true). Names of its settings:"
az functionapp config appsettings list -n "$APP" -g "$RG" --query "[].name" -o tsv
