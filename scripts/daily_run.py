"""The whole daily job, by hand: classify once, then log bills, label mail and send the digest.

Run:  uv run python scripts/daily_run.py --hours 24
      (preview only: shows counts, writes digest_preview.html, changes and sends nothing)
Real: set DRY_RUN=false in .env, add --apply, and type `yes`. It then acts on exactly the plan it
showed, with no second round of model calls.

Labels are only ADDED and mail stays in the inbox unless KEEP_IN_INBOX=false is set in .env.
Needs the AZURE_OPENAI_* variables (and SHEET_ID to log bills). The terminal shows only counts and
error TYPES, never email text; digest_preview.html holds summaries of real mail (gitignored).
"""

import argparse
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # lets `import agent` work when run as a script

from dotenv import load_dotenv
from dry_run import RULES_PATH
from googleapiclient.discovery import build
from phase0_check import get_credentials

from agent.daily import execute_daily, prepare_daily
from agent.digest_config import load_digest_config
from agent.gmail_client import GmailClient
from agent.llm import REQUIRED, build_llm
from agent.nodes.classify import build_classifier
from agent.nodes.extract import build_extractor
from agent.nodes.summarize import build_group_summarizer, build_summarizer
from agent.nodes.transactions import build_transaction_extractor
from agent.profile import load_profile
from agent.rules import load_rules
from agent.sheets_client import SheetsClient

load_dotenv(ROOT / ".env")

CONFIG_PATH = ROOT / "digest.toml"  # optional; defaults are used when absent
PROFILE_PATH = ROOT / "profile.toml"  # optional personal taste; neutral when absent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=float, default=24)
    parser.add_argument("--max", type=int, default=500, dest="max_results")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Do it for real. Also needs DRY_RUN=false in .env and a typed `yes`.",
    )
    parser.add_argument("--preview", type=Path, default=ROOT / "digest_preview.html")
    args = parser.parse_args()

    env_allows = os.environ.get("DRY_RUN", "true").strip().lower() == "false"
    if args.apply and not env_allows:
        sys.exit(
            "Refusing to apply: set DRY_RUN=false in .env as well as passing --apply."
        )
    missing = [name for name in REQUIRED if not os.environ.get(name)]
    if missing:
        sys.exit(f"Missing in .env: {', '.join(missing)}")
    keep_in_inbox = os.environ.get("KEEP_IN_INBOX", "true").strip().lower() != "false"

    creds = get_credentials()
    llm = build_llm()
    gmail = GmailClient(build("gmail", "v1", credentials=creds))
    profile = load_profile(PROFILE_PATH)
    sheet_id = os.environ.get("SHEET_ID", "")
    sheets = (
        SheetsClient(build("sheets", "v4", credentials=creds), sheet_id)
        if sheet_id
        else None
    )
    until = datetime.now(UTC)

    plan = prepare_daily(
        gmail,
        load_rules(RULES_PATH),
        load_digest_config(CONFIG_PATH),
        build_classifier(llm, profile),
        build_extractor(llm),
        build_summarizer(llm),
        build_group_summarizer(llm),
        since=until - timedelta(hours=args.hours),
        until=until,
        keep_in_inbox=keep_in_inbox,
        max_results=args.max_results,
        transaction_extractor=build_transaction_extractor(llm),
        profile=profile,
    )
    args.preview.write_text(plan.rendered.html)

    print(f"Digest subject: {plan.rendered.subject}")
    for section in plan.content.sections:
        print(f"  {section.title}: {section.count} mails")
    if plan.content.other_count:
        print(f"  Not in any section: {plan.content.other_count}")
    how = "added to" if keep_in_inbox else "moved out of the inbox into"
    print(
        f"\nWould label {plan.planned_labels} mails ({how} their labels; Gmail is only touched on --apply)."
    )
    print(
        f"Would offer {plan.planned_rows} bill/receipt rows to the Sheet"
        + ("" if sheets else " (SHEET_ID not set: skipped)")
        + "."
    )
    print(f"Would send the digest to your own address. Preview: {args.preview}")

    if not args.apply:
        print("\nPreview only: nothing was changed or sent.")
        return

    answer = input(
        f"\nDo all of that now (digest goes to {gmail.my_address()})? Type yes: "
    )
    if answer.strip().lower() != "yes":
        print("Cancelled. Nothing was changed or sent.")
        return
    result = execute_daily(plan, gmail, sheets)
    print(f"\nSheet rows added: {len(result.rows_added)}")
    if result.labelled is not None:
        print(f"Mail labelled: {len(result.labelled.moved)}")
    print(
        f"Digest sent: {'yes, message id ' + result.digest_message_id if result.digest_message_id else 'NO'}"
    )
    if result.errors:
        print("Problems: " + ", ".join(result.errors))
        sys.exit(1)


if __name__ == "__main__":
    main()
