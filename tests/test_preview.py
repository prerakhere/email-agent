from agent.nodes.classify import build_inputs
from agent.report import format_sent_preview
from agent.schemas import Category, Email

RULES = {"bytebytego.com": Category.NEWSLETTERS}


def make_email(mid="1", sender="Bank <alerts@bank.com>", subject="s", body="") -> Email:
    return Email(
        id=mid, thread_id="t", sender=sender, subject=subject, body_preview=body
    )


def test_build_inputs_redacts_trims_and_keeps_real_sender():
    email = make_email(
        subject="OTP is 4821", body="Card 4111 1111 1111 1111 " + "x" * 2000
    )
    inputs = build_inputs(email)
    assert inputs["sender"] == "Bank <alerts@bank.com>"
    assert inputs["subject"] == "OTP is [REDACTED]"
    assert inputs["body_preview"].startswith("Card [NUMBER] ")
    assert len(inputs["body_preview"]) == 500
    assert inputs["has_unsubscribe"] == "no"


def test_preview_shows_the_redacted_text_not_the_original():
    preview = format_sent_preview([make_email(body="Card 4111 1111 1111 1111")], RULES)
    assert "Card [NUMBER]" in preview
    assert "4111" not in preview


def test_preview_lists_only_mail_that_would_reach_the_llm():
    emails = [
        make_email("1", sender="a@bytebytego.com", subject="rule matched"),
        make_email("2", sender="x@other.com", subject="goes to llm"),
    ]
    preview = format_sent_preview(emails, RULES)
    assert "goes to llm" in preview
    assert "rule matched" not in preview


def test_preview_says_how_many_were_skipped_because_a_rule_matched():
    emails = [
        make_email("1", sender="a@bytebytego.com"),
        make_email("2", sender="b@bytebytego.com"),
        make_email("3", sender="x@other.com"),
    ]
    preview = format_sent_preview(emails, RULES)
    assert "1 of 3 emails would be sent to the LLM" in preview
    assert "2 matched a rule and would not be sent" in preview


def test_preview_when_nothing_would_be_sent():
    preview = format_sent_preview([make_email(sender="a@bytebytego.com")], RULES)
    assert "Nothing would be sent to the LLM" in preview
    assert "1 matched a rule" in preview


def test_preview_with_no_emails():
    assert "Nothing would be sent to the LLM" in format_sent_preview([], RULES)
