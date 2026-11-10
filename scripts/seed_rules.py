"""Phase 2: learn sender -> category rules from mail you already filed, write rules.json.

Run:  uv run python scripts/seed_rules.py --per-label 200
Reads Gmail only (sender headers, no bodies, no LLM); never modifies Gmail.
rules.json contains sender addresses, so keep it out of git.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # lets `import agent` work when run as a script

from googleapiclient.discovery import build
from phase0_check import get_credentials

from agent.gmail_client import GmailClient
from agent.profile import load_profile
from agent.rules import labels_to_categories, learn_rules, save_rules

RULES_PATH = ROOT / "rules.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-label", type=int, default=200, dest="per_label")
    parser.add_argument("--min-messages", type=int, default=2, dest="min_messages")
    args = parser.parse_args()

    gmail = GmailClient(build("gmail", "v1", credentials=get_credentials()))
    label_ids = gmail.label_ids_by_name()
    profile = load_profile(ROOT / "profile.toml")
    mapping = labels_to_categories(label_ids, profile.learn_from_folders)
    if not mapping:
        sys.exit(
            "None of your labels match learn_from_folders in profile.toml "
            "(copy profile.example.toml to start)."
        )

    samples = []
    for name, category in sorted(mapping.items()):
        senders = gmail.fetch_senders(label_ids[name], max_results=args.per_label)
        print(f"{name}: {len(senders)} messages -> {category.value}")
        samples.extend((sender, category) for sender in senders)

    rules = learn_rules(samples, min_messages=args.min_messages)
    save_rules(rules, RULES_PATH)

    by_category = Counter(c.value for c in rules.values())
    domains = sorted(k for k in rules if "@" not in k)
    print(
        f"\nLearned {len(rules)} rules from {len(samples)} messages: {dict(by_category)}"
    )
    print(f"Domain rules ({len(domains)}): {', '.join(domains) or '(none)'}")
    print(f"Saved to {RULES_PATH.name}. Review it before relying on it.")


if __name__ == "__main__":
    main()
