import re
from datetime import UTC, datetime

from agent.digest import DigestContent, EmailRef, SectionSummary
from agent.digest_email import render_digest
from agent.nodes.summarize import EmailSummary, GroupSummary

SINCE = datetime(2026, 11, 7, 2, 30, tzinfo=UTC)  # 8:00 AM IST on 7 Nov
UNTIL = datetime(2026, 11, 8, 2, 30, tzinfo=UTC)  # 8:00 AM IST on 8 Nov


def entry(mid="m1", subject="Interview", summary="They want Tuesday.", points=(), **kw):
    return EmailSummary(
        email_id=mid,
        sender="Jane <jane@corp.com>",
        subject=subject,
        summary=summary,
        action_points=list(points),
        **kw,
    )


def important(items, omitted=0):
    return SectionSummary(
        title="Important",
        mode="per_email",
        count=len(items) + omitted,
        items=items,
        omitted=omitted,
    )


def render(sections, other=0, total=None):
    total = total if total is not None else sum(s.count for s in sections) + other
    content = DigestContent(sections=sections, other_count=other, total=total)
    return render_digest(content, SINCE, UNTIL)


def test_the_subject_has_the_date_and_the_count():
    rendered = render([important([entry()])])
    assert "8 Nov" in rendered.subject and "1 email" in rendered.subject
    assert "2 emails" in render([important([entry(), entry("m2")])]).subject


def test_the_window_is_shown_in_indian_time():
    rendered = render([important([entry()])])
    assert (
        "8:00 AM" in rendered.text
        and "7 Nov" in rendered.text
        and "8 Nov" in rendered.text
    )


def test_a_section_shows_its_title_count_summary_and_action_points():
    rendered = render([important([entry(points=["Reply by Friday", "Send CV"])])])
    assert "Important (1)" in rendered.html and "Important (1)" in rendered.text
    assert "They want Tuesday." in rendered.html
    assert (
        "<li>Reply by Friday</li>" in rendered.html
        and "<li>Send CV</li>" in rendered.html
    )
    assert "Reply by Friday" in rendered.text and "Send CV" in rendered.text


def test_every_subject_links_to_its_gmail_message_and_only_to_gmail():
    rendered = render([important([entry("abc123"), entry("def456")])])
    hrefs = re.findall(r'href="([^"]+)"', rendered.html)
    assert "https://mail.google.com/mail/u/0/#all/abc123" in hrefs
    assert all(h.startswith("https://mail.google.com/") for h in hrefs)
    assert "https://mail.google.com/mail/u/0/#all/def456" in rendered.text


def test_text_from_emails_and_the_model_is_escaped_in_the_html():
    nasty = entry(
        subject="<script>alert(1)</script>",
        summary='Click <a href="https://evil.example">here</a> & win',
    )
    html = render([important([nasty])]).html
    assert "<script" not in html and '<a href="https://evil' not in html
    assert "&lt;script&gt;" in html and "&amp; win" in html


def test_an_entry_without_a_model_summary_says_so_and_keeps_the_subject():
    rendered = render(
        [important([entry(subject="Weird mail", summary="Weird mail", fallback=True)])]
    )
    assert "Weird mail" in rendered.html and "Summary unavailable" in rendered.html
    assert "Summary unavailable" in rendered.text


def test_omitted_mail_is_counted_not_hidden():
    rendered = render([important([entry()], omitted=3)])
    assert "+3 more" in rendered.html and "+3 more" in rendered.text


def group_section(summary="Mostly Python roles.", fallback=False, refs=None):
    refs = (
        refs
        if refs is not None
        else [EmailRef(email_id="g1", sender="Naukri <n@x.com>", subject="5 new jobs")]
    )
    return SectionSummary(
        title="Job alerts",
        mode="group",
        count=12,
        group=GroupSummary(count=12, summary=summary, fallback=fallback),
        refs=refs,
    )


def test_a_group_section_shows_its_paragraph_and_linked_examples():
    rendered = render([group_section()])
    assert "Job alerts (12)" in rendered.html
    assert "Mostly Python roles." in rendered.html
    assert 'href="https://mail.google.com/mail/u/0/#all/g1"' in rendered.html
    assert "5 new jobs" in rendered.text


def test_a_group_with_no_summary_says_so():
    rendered = render([group_section(summary="", fallback=True)])
    assert "Summary unavailable" in rendered.html


def test_mail_no_section_covers_is_mentioned_as_a_count():
    rendered = render([important([entry()])], other=7)
    assert (
        "Plus 7 other emails" in rendered.html
        and "Plus 7 other emails" in rendered.text
    )
    assert "other email" not in render([important([entry()])]).text


def test_an_empty_window_says_so():
    rendered = render([], total=0)
    assert "No new mail" in rendered.html and "No new mail" in rendered.text
    assert "0 emails" in rendered.subject


def test_the_text_version_has_no_html_tags():
    rendered = render([important([entry(points=["Do it"])]), group_section()], other=2)
    assert not re.search(r"</?(p|ul|li|div|h2|a|b|i|span)\b", rendered.text)
