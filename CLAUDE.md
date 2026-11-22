# Gmail Agent

Daily Azure Function (Python 3.12) that triages personal Gmail with a LangGraph pipeline + Azure OpenAI
gpt-4.1-mini: classify (with one re-read when unsure), label and move labelled mail out of the inbox,
summarize newsletters/important mail, log bills to a Google Sheet, send a digest email, and offer
promotions for a clean-up the owner approves on a signed page (paused LangGraph thread, saved in Azure
DocumentDB). Full plan: `~/.claude/plans/pasted-content-id-e06a-what-flickering-bunny.md`
(phases 0-8: validate Gmail access -> dry-run graph -> rules seeding -> apply labels -> bills sheet ->
summaries/digest -> deploy -> backfill -> iterate).

## Commands
- `uv sync` install deps; `uv run pytest` tests; `uv run ruff check .` / `uv run ruff format .`

## Workflow rules
- **TDD preferred**: write the failing test first, then the code. Not a hard rule for exploratory scripts (Phase 0).
- Work directly on `main`; small atomic commits (one logical change, message explains why). Tag phase ends (`phase-N-done`).
- Run the phase's verification (tests / script) before every commit.
- `DRY_RUN=true` by default; never modify real Gmail unless explicitly enabled.
- Labels (hybrid): file into the user's EXISTING labels when there is a clear match (e.g. Money/*, Newsletters, Read Later/*);
  otherwise fall back to `Agent/...` (Agent/Needs-Review, Agent/Job-Alerts). Move = add label + remove INBOX; never archive without a label.
- **Never permanently delete mail.** The only mail that may go to Gmail's Bin (recoverable for 30 days) is promotions the
  owner ticked on the approval page; nothing is binned without that click. The Gmail scope (`gmail.modify`) cannot delete permanently.
  The agent never invents free-form labels: unmatched mail -> Agent/Needs-Review; new labels are only suggested in the digest (Phase 8) and need user approval.

## Production settings (Azure)
- `DRY_RUN`, `KEEP_IN_INBOX` and `CLEANUP_ENABLED` are the owner's switches; change them only when asked.
- `scripts/push_settings.sh` deliberately resets them to the safe defaults (true, true, false): never run it to change
  one setting; set that setting alone with `az functionapp config appsettings set`.
- Secrets live in Key Vault (`gmail-agent-kv-pj01`) and reach the app as references; the checkpoint database is
  `email-agent-mongo-pj01` (DocumentDB free tier). Its firewall allows Azure services only; add your IP only for a
  one-off check and remove it afterwards.

## Logging
- After each significant change/milestone, append a dated entry to `WORKLOG.md` (gitignored). Concept explanations go in `LEARNING.md` via `/learn`.

## Secrets
- Never read, print, or commit `credentials.json`, `token*.json`, `.env`, `local.settings.json` (denied in `.claude/settings.json`).
- Scripts must never print tokens or email bodies' secrets to the terminal.

## Learning
- User is new to LangGraph/LangChain/LangSmith: use their features broadly and explain each new concept briefly
  before using it. Record explanations in `LEARNING.md` (gitignored) when asked.

## Communication
- Before every file change, command, or commit, explain in 1-2 plain-English sentences what it does and why; after, say what changed.
- Never chain write-tests, write-code, and commit without narrating each step. Use plain words in command descriptions.
