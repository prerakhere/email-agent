"""Free, rule-based classification that runs before any LLM call.

Rules map a sender address ("a@b.com") or a domain ("b.com") to a Category.
Returning None means "no rule matched - ask the LLM".
"""

from collections.abc import Mapping

from agent.schemas import Category, Classification, Email

ADDRESS_CONFIDENCE = 1.0
DOMAIN_CONFIDENCE = 0.95


def _parent_domains(domain: str) -> list[str]:
    """'mail.a.com' -> ['mail.a.com', 'a.com'] (whole labels only, never bare 'com')."""
    labels = domain.split(".")
    return [".".join(labels[i:]) for i in range(len(labels) - 1)]


def prefilter(email: Email, rules: Mapping[str, Category]) -> Classification | None:
    lowered = {key.lower(): category for key, category in rules.items()}
    address = email.sender_address
    if "@" not in address:
        return None

    if address in lowered:
        return Classification(
            category=lowered[address],
            confidence=ADDRESS_CONFIDENCE,
            reason=f"sender rule: {address}",
            source="rule",
        )
    for domain in _parent_domains(email.sender_domain):
        if domain in lowered:
            return Classification(
                category=lowered[domain],
                confidence=DOMAIN_CONFIDENCE,
                reason=f"domain rule: {domain}",
                source="rule",
            )
    return None
