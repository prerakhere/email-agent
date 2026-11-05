"""Learn sender -> category rules from mail the user has already filed by hand.

A wrong rule silently misfiles mail with no LLM check, so learning is deliberately cautious:
- a sender needs a minimum number of messages and ~90% agreement,
- Important / Needs-Review are never learned (those need a human or the LLM),
- domain-wide rules exist only for newsletters (a bank's domain also sends OTPs and alerts),
- shared mail providers (gmail.com ...) never get a domain rule.
"""

import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from email.utils import parseaddr
from pathlib import Path

from agent.schemas import Category

MIN_AGREEMENT = 0.9
NEVER_LEARN = {Category.IMPORTANT, Category.NEEDS_REVIEW}
SHARED_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "yahoo.com",
    "yahoo.co.in",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "icloud.com",
    "proton.me",
    "protonmail.com",
    "rediffmail.com",
}


def learn_rules(
    samples: Iterable[tuple[str, Category]], min_messages: int = 2
) -> dict[str, Category]:
    """samples = (sender header or address, category the user filed it under)."""
    by_address: dict[str, Counter] = defaultdict(Counter)
    for sender, category in samples:
        address = parseaddr(sender)[1].lower()
        if "@" in address:
            by_address[address][category] += 1

    rules: dict[str, Category] = {}
    for address, counts in by_address.items():
        total = sum(counts.values())
        category, top = counts.most_common(1)[0]
        if (
            total >= min_messages
            and top / total >= MIN_AGREEMENT
            and category not in NEVER_LEARN
        ):
            rules[address] = category

    domains: dict[str, dict[str, Counter]] = defaultdict(dict)
    for address, counts in by_address.items():
        domains[address.rpartition("@")[2]][address] = counts
    for domain, addresses in domains.items():
        if domain in SHARED_DOMAINS or len(addresses) < 2:
            continue
        combined = sum(addresses.values(), Counter())
        if (
            set(combined) == {Category.NEWSLETTERS}
            and sum(combined.values()) >= min_messages
        ):
            rules[domain] = Category.NEWSLETTERS
    return rules


def save_rules(rules: dict[str, Category], path: Path) -> None:
    path.write_text(
        json.dumps({k: v.value for k, v in sorted(rules.items())}, indent=2) + "\n"
    )


def load_rules(path: Path) -> dict[str, Category]:
    if not path.exists():
        return {}
    return {key: Category(value) for key, value in json.loads(path.read_text()).items()}
