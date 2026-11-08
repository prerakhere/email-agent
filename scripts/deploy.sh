#!/usr/bin/env bash
# Deploy the code to the Azure Function App:   bash scripts/deploy.sh
#
# 1. Lint and tests must pass first.
# 2. requirements.txt is generated from uv.lock (runtime dependencies only; it is gitignored and
#    rebuilt every time so it can never drift from the lockfile).
# 3. Core Tools uploads the app and Azure builds it. What is NOT uploaded is decided by .funcignore
#    (secrets, tests, notes). local.settings.json is never published.
set -euo pipefail
cd "$(dirname "$0")/.."

APP=gmail-agent-func-pj01

echo "1/3 Lint and tests ..."
uv run ruff check .
uv run pytest -q

echo "2/3 Writing requirements.txt from uv.lock ..."
uv export --no-dev --no-hashes --no-emit-project -o requirements.txt

echo "3/3 Publishing to $APP (Azure builds it; this takes a few minutes) ..."
func azure functionapp publish "$APP" --python
