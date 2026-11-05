from agent.report import format_table
from agent.schemas import Category, Proposal


def make_proposal(**kwargs) -> Proposal:
    defaults = {
        "email_id": "1",
        "sender": "Shop <deals@shop.com>",
        "subject": "50% off",
        "category": Category.PROMOTIONS,
        "label": "Agent/Promotions",
        "confidence": 0.9,
        "reason": "sale",
        "source": "llm",
    }
    return Proposal(**{**defaults, **kwargs})


def test_empty_list_says_no_emails():
    assert format_table([]) == "No emails to show."


def test_table_has_header_and_one_row_per_proposal():
    lines = format_table([make_proposal(), make_proposal(email_id="2")]).splitlines()
    assert "Sender" in lines[0] and "Subject" in lines[0] and "Label" in lines[0]
    rows = [line for line in lines if "deals@shop.com" in line]
    assert len(rows) == 2


def test_row_shows_category_label_confidence_and_source():
    table = format_table([make_proposal(confidence=0.857, source="rule")])
    assert "promotions" in table
    assert "Agent/Promotions" in table
    assert "0.86" in table
    assert "rule" in table


def test_long_values_are_truncated_with_an_ellipsis():
    table = format_table([make_proposal(subject="x" * 200)])
    assert "x" * 200 not in table
    assert "…" in table


def test_summary_counts_categories_and_rule_decisions():
    proposals = [
        make_proposal(email_id="1", category=Category.NEWSLETTERS, source="rule"),
        make_proposal(email_id="2", category=Category.NEWSLETTERS, source="rule"),
        make_proposal(email_id="3", category=Category.PROMOTIONS, source="llm"),
    ]
    summary = format_table(proposals).splitlines()[-1]
    assert "3 emails" in summary
    assert "2 decided by rules" in summary
    assert "newsletters=2" in summary
    assert "promotions=1" in summary
