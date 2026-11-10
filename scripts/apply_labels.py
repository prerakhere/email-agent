"""Phases 3-4: classify recent inbox mail, show the plan, and (only if you ask) label it and log
its bills/receipts to the Google Sheet.

Run:  uv run python scripts/apply_labels.py --days 3 --max 20          (plan only, changes nothing)
Real: set DRY_RUN=false in .env, then add --apply; you must also type `yes` at the prompt.

Add --no-label to log bills/receipts to the sheet only, leaving every label in Gmail untouched.

By default (KEEP_IN_INBOX unset or true) mail is only LABELLED and stays in the inbox.
Set KEEP_IN_INBOX=false later to also remove INBOX; then Important, Needs-Review and starred mail
still stay. Nothing is ever deleted. Never prints keys or email bodies.

Bills/receipts: one run extracts their details AND labels them, because already-labelled mail is
skipped on later runs. On --apply the sheet rows are written FIRST, then the labels: if the sheet
write fails the mail stays unlabelled and the next run retries it. Needs SHEET_ID in .env.
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # lets `import agent` work when run as a script

from dotenv import load_dotenv
from dry_run import RULES_PATH
from googleapiclient.discovery import build
from phase0_check import get_credentials

from agent.apply import apply_proposals
from agent.execute import execute_run
from agent.gmail_client import GmailClient
from agent.graph import BILLING, build_graph, collect_bill_items
from agent.llm import REQUIRED, build_llm
from agent.nodes.classify import build_classifier
from agent.nodes.extract import build_extractor
from agent.profile import load_profile
from agent.report import format_apply_report, format_bill_plan, format_table
from agent.rules import load_rules
from agent.sheets_client import SheetsClient

load_dotenv(ROOT / ".env")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--max", type=int, default=20, dest="max_results")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually move mail. Also needs DRY_RUN=false in .env and a typed `yes`.",
    )
    parser.add_argument(
        "--no-label",
        action="store_true",
        help="Only log bills/receipts to the sheet; do not touch any labels in Gmail.",
    )
    args = parser.parse_args()
    label = not args.no_label

    keep_in_inbox = os.environ.get("KEEP_IN_INBOX", "true").strip().lower() != "false"
    env_allows = os.environ.get("DRY_RUN", "true").strip().lower() == "false"
    if args.apply and not env_allows:
        sys.exit(
            "Refusing to apply: set DRY_RUN=false in .env as well as passing --apply."
        )

    missing = [name for name in REQUIRED if not os.environ.get(name)]
    if missing:
        sys.exit(f"Missing in .env: {', '.join(missing)}")

    llm = build_llm()
    creds = get_credentials()
    gmail = GmailClient(build("gmail", "v1", credentials=creds))
    graph = build_graph(
        gmail,
        load_rules(RULES_PATH),
        build_classifier(llm),
        days=args.days,
        max_results=args.max_results,
        extractor=build_extractor(llm),
        profile=load_profile(ROOT / "profile.toml"),
    )
    state = graph.invoke({}, config={"tags": ["apply"], "metadata": {"phase": 4}})
    print(format_table(state["proposals"]))
    print()

    plan = apply_proposals(
        state["proposals"], gmail, dry_run=True, keep_in_inbox=keep_in_inbox
    )
    print(
        format_apply_report(plan, dry_run=True)
        if label
        else "Labelling skipped (--no-label): no labels will be touched."
    )

    items = collect_bill_items(state)
    logged = {email.id for email, _, _ in items}
    missed = sum(
        1
        for email in state["emails"]
        if state["classifications"][email.id].category in BILLING
        and email.id not in logged
    )
    print()
    print(format_bill_plan(items, missed))
    if not args.apply or not ((label and plan.planned) or items):
        return

    sheet_id = os.environ.get("SHEET_ID", "")
    if items and not sheet_id:
        sys.exit(
            "Bills were found but SHEET_ID is not set in .env. Nothing was changed."
        )

    what = "Label" if keep_in_inbox else "Move out of the inbox"
    to_do = f"{what} {len(plan.planned)} emails and add" if label else "Add"
    answer = input(f"\n{to_do} up to {len(items)} sheet rows? Type yes: ")
    if answer.strip().lower() != "yes":
        print("Cancelled. Nothing was changed.")
        return

    sheets = (
        SheetsClient(build("sheets", "v4", credentials=creds), sheet_id)
        if items
        else None
    )
    outcome = execute_run(
        state, gmail, sheets, label=label, keep_in_inbox=keep_in_inbox
    )
    if items:
        added = len(outcome.rows_added)
        print(
            f"\n{added} rows added to the sheet ({len(items) - added} already logged)."
        )
    if outcome.labelled is not None:
        print("\n" + format_apply_report(outcome.labelled, dry_run=False))


if __name__ == "__main__":
    main()
