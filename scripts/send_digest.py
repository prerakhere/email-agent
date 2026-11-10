"""Create the daily digest for the last N hours and (only if you ask) email it to yourself.

Run:  uv run python scripts/send_digest.py --hours 24
      (preview only: writes digest_preview.html and sends nothing)
Send: set DRY_RUN=false in .env, add --send, and type `yes` at the prompt.

Needs the AZURE_OPENAI_* variables in .env. The terminal shows only the subject, per-section counts
and the preview path, never email text. digest_preview.html holds summaries of your real mail
(gitignored). The digest only reads and summarises; it never labels, moves or deletes anything.
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

from agent.digest_config import load_digest_config
from agent.digest_run import create_digest
from agent.gmail_client import GmailClient
from agent.llm import REQUIRED, build_llm
from agent.nodes.classify import build_classifier
from agent.nodes.extract import build_extractor
from agent.nodes.summarize import build_group_summarizer, build_summarizer
from agent.nodes.transactions import build_transaction_extractor
from agent.profile import load_profile
from agent.rules import load_rules

load_dotenv(ROOT / ".env")

CONFIG_PATH = ROOT / "digest.toml"  # optional; defaults are used when absent
PROFILE_PATH = ROOT / "profile.toml"  # optional personal taste; neutral when absent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=float, default=24)
    parser.add_argument("--max", type=int, default=500, dest="max_results")
    parser.add_argument(
        "--send",
        action="store_true",
        help="Email the digest to yourself. Also needs DRY_RUN=false in .env and a typed `yes`.",
    )
    parser.add_argument("--preview", type=Path, default=ROOT / "digest_preview.html")
    args = parser.parse_args()

    env_allows = os.environ.get("DRY_RUN", "true").strip().lower() == "false"
    if args.send and not env_allows:
        sys.exit(
            "Refusing to send: set DRY_RUN=false in .env as well as passing --send."
        )
    missing = [name for name in REQUIRED if not os.environ.get(name)]
    if missing:
        sys.exit(f"Missing in .env: {', '.join(missing)}")

    llm = build_llm()
    gmail = GmailClient(build("gmail", "v1", credentials=get_credentials()))
    profile = load_profile(PROFILE_PATH)
    until = datetime.now(UTC)
    since = until - timedelta(hours=args.hours)

    content, rendered = create_digest(
        gmail,
        load_rules(RULES_PATH),
        load_digest_config(CONFIG_PATH),
        build_classifier(llm, profile),
        build_summarizer(llm),
        build_group_summarizer(llm),
        since=since,
        until=until,
        max_results=args.max_results,
        extractor=build_extractor(llm),
        transaction_extractor=build_transaction_extractor(llm),
        profile=profile,
    )
    args.preview.write_text(rendered.html)

    print(f"Subject: {rendered.subject}")
    for section in content.sections:
        shown = len(section.items) if section.mode == "per_email" else len(section.refs)
        no_summary = sum(1 for i in section.items if i.fallback)
        if section.group is not None and section.group.fallback:
            no_summary = 1
        print(
            f"  {section.title}: {section.count} mails, {shown} shown, "
            f"{section.omitted} omitted, {no_summary} without a summary"
        )
    if content.other_count:
        print(f"  Not in any section: {content.other_count}")
    print(f"\nPreview written to {args.preview} (open it in a browser).")

    if not args.send:
        print("Preview only: nothing was sent.")
        return

    answer = input(f"\nSend this digest to {gmail.my_address()}? Type yes: ")
    if answer.strip().lower() != "yes":
        print("Cancelled. Nothing was sent.")
        return
    message_id = gmail.send_to_self(rendered.subject, rendered.text, rendered.html)
    print(f"Sent (Gmail message id {message_id}).")


if __name__ == "__main__":
    main()
