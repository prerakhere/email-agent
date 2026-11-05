"""Phase 1 dry-run: classify recent inbox mail and PRINT proposed labels. Never modifies Gmail.

Run:  uv run python scripts/dry_run.py --days 3 --max 20
Needs the AZURE_OPENAI_* variables in .env. Prints sender/subject/category only (no bodies, no keys).
If LANGSMITH_TRACING=true and LANGSMITH_API_KEY are set in .env, every run is traced in LangSmith.
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from googleapiclient.discovery import build
from langchain_openai import AzureChatOpenAI
from phase0_check import get_credentials

from agent.gmail_client import GmailClient
from agent.graph import build_graph
from agent.nodes.classify import build_classifier
from agent.report import format_table
from agent.schemas import Category

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Temporary hand-written rules until Phase 2 seeds them from your existing folders.
RULES = {
    "bytebytego.com": Category.NEWSLETTERS,
    "quastor.org": Category.NEWSLETTERS,
}

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
    args = parser.parse_args()

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
        RULES,
        build_classifier(llm),
        days=args.days,
        max_results=args.max_results,
    )

    print("DRY RUN: reading Gmail only, nothing will be changed.\n")
    state = graph.invoke({}, config={"tags": ["dry-run"], "metadata": {"phase": 1}})
    print(format_table(state["proposals"]))


if __name__ == "__main__":
    main()
