from unittest.mock import MagicMock

from agent.apply import apply_proposals
from agent.schemas import Category, Proposal


def proposal(
    email_id="m1", category=Category.JOB_ALERTS, label="Agent/Job-Alerts", **kw
):
    return Proposal(
        **{
            "email_id": email_id,
            "sender": "x@y.com",
            "subject": "s",
            "category": category,
            "label": label,
            "confidence": 0.9,
            "reason": "r",
            "source": "llm",
            **kw,
        }
    )


def fake_gmail():
    gmail = MagicMock()
    gmail.ensure_label.side_effect = lambda name: f"id:{name}"
    return gmail


def test_dry_run_plans_moves_but_makes_no_gmail_calls():
    gmail = fake_gmail()
    result = apply_proposals([proposal()], gmail, dry_run=True)
    assert [p.email_id for p in result.planned] == ["m1"]
    assert result.moved == []
    gmail.ensure_label.assert_not_called()
    gmail.move_to_label.assert_not_called()


def test_real_run_moves_each_planned_email_into_its_label():
    gmail = fake_gmail()
    result = apply_proposals(
        [proposal("m1"), proposal("m2", Category.NEWSLETTERS, "Newsletters")],
        gmail,
        dry_run=False,
    )
    assert [p.email_id for p in result.moved] == ["m1", "m2"]
    gmail.move_to_label.assert_any_call("m1", "id:Agent/Job-Alerts")
    gmail.move_to_label.assert_any_call("m2", "id:Newsletters")


def test_important_mail_is_never_moved():
    gmail = fake_gmail()
    result = apply_proposals(
        [proposal(category=Category.IMPORTANT, label="Agent/Important")],
        gmail,
        dry_run=False,
    )
    assert result.moved == [] and result.planned == []
    assert "important" in result.skipped[0][1].lower()
    gmail.move_to_label.assert_not_called()


def test_needs_review_mail_stays_in_the_inbox():
    gmail = fake_gmail()
    result = apply_proposals(
        [proposal(category=Category.NEEDS_REVIEW, label="Agent/Needs-Review")],
        gmail,
        dry_run=False,
    )
    assert result.moved == []
    gmail.move_to_label.assert_not_called()


def test_starred_mail_is_never_moved():
    gmail = fake_gmail()
    result = apply_proposals([proposal(starred=True)], gmail, dry_run=False)
    assert result.moved == []
    assert "starred" in result.skipped[0][1].lower()
    gmail.move_to_label.assert_not_called()


def test_each_label_is_looked_up_or_created_only_once():
    gmail = fake_gmail()
    apply_proposals(
        [proposal("m1"), proposal("m2"), proposal("m3")], gmail, dry_run=False
    )
    gmail.ensure_label.assert_called_once_with("Agent/Job-Alerts")
    assert gmail.move_to_label.call_count == 3


def test_skipped_mail_does_not_create_its_label():
    gmail = fake_gmail()
    apply_proposals(
        [proposal(category=Category.IMPORTANT, label="Agent/Important")],
        gmail,
        dry_run=False,
    )
    gmail.ensure_label.assert_not_called()


def test_dry_run_is_the_default():
    gmail = fake_gmail()
    apply_proposals([proposal()], gmail)
    gmail.move_to_label.assert_not_called()
