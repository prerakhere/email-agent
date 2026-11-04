from agent.nodes.prefilter import prefilter
from agent.schemas import Category, Email


def make_email(sender: str, **kwargs) -> Email:
    return Email(id="m1", thread_id="t1", sender=sender, subject="s", **kwargs)


RULES = {
    "alerts@hdfcbank.net": Category.BILLS,
    "hdfcbank.net": Category.NOTIFICATIONS,
    "bytebytego.com": Category.NEWSLETTERS,
}


def test_exact_address_rule_matches_with_full_confidence():
    result = prefilter(make_email("HDFC <alerts@hdfcbank.net>"), RULES)
    assert result is not None
    assert result.category == Category.BILLS
    assert result.confidence == 1.0
    assert result.source == "rule"
    assert "alerts@hdfcbank.net" in result.reason


def test_address_rule_beats_domain_rule():
    # hdfcbank.net is NOTIFICATIONS, but this exact address is BILLS.
    result = prefilter(make_email("alerts@hdfcbank.net"), RULES)
    assert result.category == Category.BILLS


def test_domain_rule_matches_with_slightly_lower_confidence():
    result = prefilter(make_email("news@bytebytego.com"), RULES)
    assert result.category == Category.NEWSLETTERS
    assert result.confidence == 0.95
    assert result.source == "rule"


def test_subdomain_matches_parent_domain_rule():
    result = prefilter(make_email("hi@mail.bytebytego.com"), RULES)
    assert result.category == Category.NEWSLETTERS


def test_lookalike_domain_does_not_match():
    # "notbytebytego.com" must not match the "bytebytego.com" rule.
    assert prefilter(make_email("x@notbytebytego.com"), RULES) is None


def test_matching_ignores_case_in_rules_and_sender():
    result = prefilter(
        make_email("X@BYTEBYTEGO.COM"), {"ByteByteGo.com": Category.NEWSLETTERS}
    )
    assert result.category == Category.NEWSLETTERS


def test_no_matching_rule_returns_none():
    assert prefilter(make_email("friend@gmail.com"), RULES) is None


def test_unsubscribe_header_alone_is_not_decisive():
    # Promotions also carry List-Unsubscribe, so it is a hint for the LLM, not a rule.
    assert prefilter(make_email("deals@shop.com", list_unsubscribe=True), RULES) is None


def test_unparseable_sender_returns_none():
    assert prefilter(make_email("undisclosed-recipients"), RULES) is None
