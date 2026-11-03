# Gmail Agent

Daily Azure Function (Python 3.12) that triages personal Gmail with a LangGraph pipeline + Azure OpenAI
GPT-4o-mini: classify, label (never archive), summarize newsletters/important mail, log bills to a Google Sheet,
and send a digest email. Full plan: `~/.claude/plans/pasted-content-id-e06a-what-flickering-bunny.md`
(phases 0-8: validate Gmail access -> dry-run graph -> rules seeding -> apply labels -> bills sheet ->
summaries/digest -> deploy -> backfill -> iterate).

## Commands
- `uv sync` install deps; `uv run pytest` tests; `uv run ruff check .` / `uv run ruff format .`

## Workflow rules
- **TDD preferred**: write the failing test first, then the code. Not a hard rule for exploratory scripts (Phase 0).
- Work directly on `main`; small atomic commits (one logical change, message explains why). Tag phase ends (`phase-N-done`).
- Run the phase's verification (tests / script) before every commit.
- `DRY_RUN=true` by default; never modify real Gmail unless explicitly enabled.
- Labels live under `Agent/...`. Move = add label + remove INBOX; never archive without a label, never delete mail.

## Secrets
- Never read, print, or commit `credentials.json`, `token*.json`, `.env`, `local.settings.json` (denied in `.claude/settings.json`).
- Scripts must never print tokens or email bodies' secrets to the terminal.

## Learning
- User is new to LangGraph/LangChain/LangSmith: use their features broadly and explain each new concept briefly
  before using it. Record explanations in `LEARNING.md` (gitignored) when asked.
