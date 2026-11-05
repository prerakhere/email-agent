"""Phase 1 dry-run: classify recent inbox mail and PRINT proposed labels. Never modifies Gmail.

Run:  uv run python scripts/dry_run.py --days 3 --max 20
Add --show-sent first to inspect the exact redacted text that would go to the LLM (no LLM call).
Needs the AZURE_OPENAI_* variables in .env (not for --show-sent). The table prints sender/subject/
category only; --show-sent also prints the REDACTED body start. Never prints keys.
If LANGSMITH_TRACING=true and LANGSMITH_API_KEY are set in .env, every run is traced in LangSmith.
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(
    0, str(ROOT)
)  # lets `import agent` work when run as a script (pytest does this itself)

from dotenv import load_dotenv
from googleapiclient.discovery import build
from langchain_openai import AzureChatOpenAI
from phase0_check import get_credentials

from agent.gmail_client import GmailClient
from agent.graph import build_graph
from agent.nodes.classify import build_classifier
from agent.report import format_sent_preview, format_table
from agent.rules import load_rules

load_dotenv(ROOT / ".env")

RULES_PATH = ROOT / "rules.json"  # written by scripts/seed_rules.py

REQUIRED = [
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_API_VERSION",
    "AZURE_OPENAI_DEPLOYMENT",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--max", type=int, default=20, dest="max_results")
    parser.add_argument(
        "--show-sent",
        action="store_true",
        help="Print the exact redacted text that WOULD be sent to the LLM, then stop. "
        "Reads Gmail only; no Azure keys needed, no LLM call.",
    )
    args = parser.parse_args()

    rules = load_rules(RULES_PATH)
    if rules:
        print(f"Loaded {len(rules)} sender rules from {RULES_PATH.name}.")
    else:
        print(
            f"No rules found ({RULES_PATH.name} missing/empty): every email goes to the LLM."
        )

    if args.show_sent:
        gmail = GmailClient(build("gmail", "v1", credentials=get_credentials()))
        emails = gmail.fetch_recent(days=args.days, max_results=args.max_results)
        print(
            "PREVIEW: nothing is sent anywhere; this is what the LLM would receive.\n"
        )
        print(format_sent_preview(emails, rules))
        return

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
        rules,
        build_classifier(llm),
        days=args.days,
        max_results=args.max_results,
    )

    print("DRY RUN: reading Gmail only, nothing will be changed.\n")
    state = graph.invoke({}, config={"tags": ["dry-run"], "metadata": {"phase": 1}})
    print(format_table(state["proposals"]))


if __name__ == "__main__":
    main()
