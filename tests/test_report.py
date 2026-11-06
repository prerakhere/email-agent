from agent.apply import ApplyResult
from agent.report import format_apply_report, format_table
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


def test_apply_report_lists_moves_and_keeps_with_reasons():
    move = make_proposal(email_id="1", subject="Weekly digest", label="Newsletters")
    keep = make_proposal(email_id="2", subject="Your interview")
    result = ApplyResult(planned=[move], skipped=[(keep, "important mail stays")])
    text = format_apply_report(result, dry_run=True)
    assert "MOVE" in text and "Weekly digest" in text and "Newsletters" in text
    assert (
        "KEEP" in text and "Your interview" in text and "important mail stays" in text
    )


def test_apply_report_dry_run_says_nothing_was_changed():
    result = ApplyResult(planned=[make_proposal()])
    text = format_apply_report(result, dry_run=True)
    assert "DRY RUN" in text and "1 would move" in text


def test_apply_report_real_run_says_how_many_were_moved():
    p = make_proposal()
    result = ApplyResult(planned=[p], moved=[p])
    text = format_apply_report(result, dry_run=False)
    assert "1 moved" in text and "DRY RUN" not in text


def test_apply_report_with_nothing_to_do():
    assert "Nothing to move" in format_apply_report(ApplyResult(), dry_run=True)


def test_apply_report_in_keep_mode_says_label_and_that_mail_stays():
    p = make_proposal(label="Newsletters")
    planned = ApplyResult(planned=[p], keep_in_inbox=True)
    text = format_apply_report(planned, dry_run=True)
    assert "LABEL" in text and "MOVE" not in text and "1 would be labelled" in text
    done = ApplyResult(planned=[p], moved=[p], keep_in_inbox=True)
    assert "1 labelled" in format_apply_report(done, dry_run=False)
