"""Phase 3: classify recent inbox mail, show the plan, and (only if you ask) move it.

Run:  uv run python scripts/apply_labels.py --days 3 --max 20          (plan only, changes nothing)
Real: set DRY_RUN=false in .env, then add --apply; you must also type `yes` at the prompt.

By default (KEEP_IN_INBOX unset or true) mail is only LABELLED and stays in the inbox.
Set KEEP_IN_INBOX=false later to also remove INBOX; then Important, Needs-Review and starred mail
still stay. Nothing is ever deleted. Never prints keys or email bodies.
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # lets `import agent` work when run as a script

from dotenv import load_dotenv
from dry_run import REQUIRED, RULES_PATH
from googleapiclient.discovery import build
from langchain_openai import AzureChatOpenAI
from phase0_check import get_credentials

from agent.apply import apply_proposals
from agent.gmail_client import GmailClient
from agent.graph import build_graph
from agent.nodes.classify import build_classifier
from agent.report import format_apply_report, format_table
from agent.rules import load_rules

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
    args = parser.parse_args()

    keep_in_inbox = os.environ.get("KEEP_IN_INBOX", "true").strip().lower() != "false"
    env_allows = os.environ.get("DRY_RUN", "true").strip().lower() == "false"
    if args.apply and not env_allows:
        sys.exit(
            "Refusing to apply: set DRY_RUN=false in .env as well as passing --apply."
        )

    missing = [name for name in REQUIRED if not os.environ.get(name)]
    if missing:
        sys.exit(f"Missing in .env: {', '.join(missing)}")

    llm = AzureChatOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ["AZURE_OPENAI_API_VERSION"],
        azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        temperature=0,
    )
    gmail = GmailClient(build("gmail", "v1", credentials=get_credentials()))
    graph = build_graph(
        gmail,
        load_rules(RULES_PATH),
        build_classifier(llm),
        days=args.days,
        max_results=args.max_results,
    )
    state = graph.invoke({}, config={"tags": ["apply"], "metadata": {"phase": 3}})
    print(format_table(state["proposals"]))
    print()

    plan = apply_proposals(
        state["proposals"], gmail, dry_run=True, keep_in_inbox=keep_in_inbox
    )
    print(format_apply_report(plan, dry_run=True))
    if not args.apply or not plan.planned:
        return

    what = "Label" if keep_in_inbox else "Move out of the inbox"
    answer = input(f"\n{what} {len(plan.planned)} emails? Type yes: ")
    if answer.strip().lower() != "yes":
        print("Cancelled. Nothing was changed.")
        return
    done = apply_proposals(
        state["proposals"], gmail, dry_run=False, keep_in_inbox=keep_in_inbox
    )
    print("\n" + format_apply_report(done, dry_run=False))


if __name__ == "__main__":
    main()
