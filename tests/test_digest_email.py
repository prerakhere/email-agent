import re
from datetime import UTC, datetime

from agent.digest import DigestContent, EmailRef, SectionSummary
from agent.digest_email import render_digest
from agent.digest_tables import TableData, TableRow
from agent.nodes.summarize import EmailSummary, GroupSummary
from agent.profile import Profile

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


def test_the_window_is_shown_in_the_profiles_time_zone():
    content = DigestContent(sections=[important([entry()])], other_count=0, total=1)
    rendered = render_digest(content, SINCE, UNTIL, Profile(timezone="Asia/Kolkata"))
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


# ---- table sections ----


def table_section(
    rows=None, omitted=0, unlisted=(), summary="2 bills: INR 7,000.00", highlight=False
):
    rows = (
        rows
        if rows is not None
        else [
            TableRow(
                email_id="b1",
                cells=["bill", "HDFC Bank", "INR 5,633.00", "2026-11-09"],
                highlight=highlight,
            ),
            TableRow(
                email_id="b2", cells=["receipt", "Amazon.in", "INR 85,004.00", "-"]
            ),
        ]
    )
    return SectionSummary(
        title="Bills and receipts",
        mode="table",
        count=len(rows) + len(unlisted),
        table=TableData(
            columns=["Type", "Biller", "Amount", "Due"],
            link_column=1,
            rows=rows,
            omitted=omitted,
            summary=summary,
            unlisted=list(unlisted),
        ),
    )


def test_a_table_section_renders_a_real_table_with_a_header_and_a_link_per_row():
    html = render([table_section()]).html
    assert "Bills and receipts (2)" in html
    data = html.split("Bills and receipts (")[1]
    assert "<table" in data and data.count("<tr") == 3  # header plus two rows
    for heading in ("Type", "Biller", "Amount", "Due"):
        assert "<th" in html and heading in html
    assert ">HDFC Bank</a>" in html and "INR 85,004.00</td>" in html
    assert 'href="https://mail.google.com/mail/u/0/#all/b1"' in html
    assert 'href="https://mail.google.com/mail/u/0/#all/b2"' in html


def test_the_totals_line_sits_above_the_table_and_is_escaped():
    html = render([table_section(summary="2 bills <b>x</b>")]).html
    assert html.index("2 bills") < html.rindex("<table")
    assert "&lt;b&gt;x&lt;/b&gt;" in html


def test_a_row_that_needs_attention_is_visibly_highlighted():
    html = render([table_section(highlight=True)]).html
    rows = html.split("Bills and receipts (")[1].split("<tr")
    first_row, second_row = rows[2], rows[3]  # [0] is before, [1] is the header
    assert "<b>" in first_row and "<b>" not in second_row


def test_table_text_from_mail_is_escaped():
    rows = [
        TableRow(email_id="t1", cells=["INR 50.00", "UPI", "<script>alert(1)</script>"])
    ]
    html = render([table_section(rows=rows)]).html
    assert "<script" not in html and "&lt;script&gt;" in html


def test_mail_with_no_amount_is_listed_below_the_table_as_linked_subjects():
    ref = EmailRef(
        email_id="u1", sender="Bajaj <i@x.com>", subject="Insta EMI Card offer"
    )
    rendered = render([table_section(unlisted=[ref])])
    assert (
        "No amount found" in rendered.html and "Insta EMI Card offer" in rendered.html
    )
    assert 'href="https://mail.google.com/mail/u/0/#all/u1"' in rendered.html
    assert (
        "No amount found" in rendered.text and "Insta EMI Card offer" in rendered.text
    )


def test_rows_beyond_the_limit_are_counted_not_hidden():
    rendered = render([table_section(omitted=4)])
    assert "+4 more not shown" in rendered.html and "+4 more not shown" in rendered.text


def test_the_text_version_shows_the_same_table_without_html():
    text = render([table_section(highlight=True)]).text
    assert "Type | Biller | Amount | Due" in text
    assert (
        "! bill | HDFC Bank | INR 5,633.00 | 2026-11-09" in text
    )  # '!' marks the highlighted row
    assert "receipt | Amazon.in | INR 85,004.00 | -" in text
    assert "2 bills: INR 7,000.00" in text
    assert "https://mail.google.com/mail/u/0/#all/b1" in text
    assert not re.search(r"</?(table|tr|td|th|b)\b", text)


# ---- Round 1b: names not addresses, the name is the link, right-aligned amounts, one line ----


def test_senders_show_their_name_not_their_address():
    html = render([important([entry()]), group_section()]).html
    assert "Jane" in html and "jane@corp.com" not in html and "n@x.com" not in html
    text = render([important([entry()]), group_section()]).text
    assert "Jane" in text and "jane@corp.com" not in text and "n@x.com" not in text


def test_a_sender_with_no_name_falls_back_to_the_address():
    nameless = entry()
    nameless.sender = "billing@shop.example"
    assert "billing@shop.example" in render([important([nameless])]).html


def test_the_biller_name_is_the_link_and_there_is_no_open_column():
    html = render([table_section()]).html
    assert ">open</a>" not in html
    assert 'href="https://mail.google.com/mail/u/0/#all/b1">HDFC Bank</a>' in html
    assert html.count("<th") == 4


def test_the_amount_column_is_right_aligned_and_the_others_are_not():
    html = render([table_section()]).html
    amount_header = re.search(r"<th[^>]*>Amount</th>", html).group(0)
    amount_cell = re.search(r"<td[^>]*>INR 5,633.00</td>", html).group(0)
    assert "text-align:right" in amount_header and "text-align:right" in amount_cell
    assert "text-align:right" not in re.search(r"<th[^>]*>Biller</th>", html).group(0)


def test_a_long_summary_is_cut_to_one_line_ending_in_an_ellipsis():
    long = "word " * 80
    html = render([important([entry(summary=long)])]).html
    shown = re.search(r'<p style="margin:4px 0 0">(.*?)</p>', html).group(1)
    assert len(shown) <= 161 and shown.endswith("…")
    assert "\n" not in shown


def test_a_short_summary_is_left_exactly_as_it_is():
    assert "They want Tuesday." in render([important([entry()])]).html
    assert "…" not in render([important([entry()])]).html


def test_a_group_summary_is_also_cut_to_one_line():
    html = render([group_section(summary="word " * 80)]).html
    assert "…" in html


# ---- Round 1c: honest counts, no useless summaries, stay under Gmail's size limit ----


def test_a_group_that_shows_fewer_links_than_it_counts_says_how_many_are_not_shown():
    section = group_section()
    section.count = 7
    rendered = render([section])
    assert "+6 more not shown" in rendered.html and "+6 more not shown" in rendered.text


def test_a_group_that_shows_every_link_adds_no_more_line():
    section = group_section()
    section.count = 1
    assert "more not shown" not in render([section]).html


def test_a_summary_that_says_the_mail_was_not_viewable_is_left_out_but_the_subject_stays():
    useless = entry(
        subject="Weekly teaching tips",
        summary="The email content is not viewable in your email client.",
    )
    rendered = render([important([useless])])
    assert "Weekly teaching tips" in rendered.html
    assert "not viewable" not in rendered.html and "not viewable" not in rendered.text
    assert "Summary unavailable" not in rendered.html


def test_a_normal_summary_mentioning_viewing_is_kept():
    ok = entry(summary="Invoice ready to view in the portal, due Friday.")
    assert "Invoice ready to view" in render([important([ok])]).html


def big_digest(n=400):
    items = [
        entry(f"m{i}", subject=f"Subject number {i} " + "x" * 40, summary="word " * 20)
        for i in range(n)
    ]
    rows = [
        TableRow(email_id=f"t{i}", cells=["bill", f"Biller {i}", "INR 1.00", "-"])
        for i in range(n)
    ]
    table = SectionSummary(
        title="Bills",
        mode="table",
        count=n,
        table=TableData(
            columns=["Type", "Biller", "Amount", "Due"],
            link_column=1,
            rows=rows,
            summary=f"{n} bills",
        ),
    )
    return [important(items), table]


def test_a_huge_digest_is_shrunk_below_the_gmail_clip_limit():
    rendered = render(big_digest())
    assert len(rendered.html.encode()) < 100_000
    assert "Shortened" in rendered.html and "Shortened" in rendered.text


def test_shrinking_never_hides_the_count_of_what_was_left_out():
    rendered = render(big_digest())
    assert "more not shown" in rendered.html


def test_a_normal_sized_digest_is_not_shortened():
    rendered = render([important([entry(), entry("m2")])])
    assert "Shortened" not in rendered.html and "Shortened" not in rendered.text


# ---- Round 2: headline, tiles and preheader ----


def due_table(highlight=True):
    return table_section(highlight=highlight)


def test_the_headline_says_what_is_important_and_due_soon_and_nothing_more():
    sections = [important([entry(), entry("m2")]), due_table()]
    rendered = render(sections, total=20)
    for page in (rendered.html, rendered.text):
        assert "2 important" in page and "1 due soon" in page
        assert "can wait" not in page


def test_a_quiet_day_says_nothing_is_urgent():
    rendered = render([group_section()], total=12)
    assert "Nothing urgent" in rendered.html and "Nothing urgent" in rendered.text
    assert "can wait" not in rendered.html


def test_an_empty_digest_says_no_new_mail_in_the_headline():
    assert "No new mail" in render([], total=0).html


def test_the_subject_does_not_change_with_the_headline():
    rendered = render([important([entry()]), due_table()], total=20)
    assert rendered.subject == "Inbox digest, 8 Nov: 20 emails"


def test_a_hidden_preheader_repeats_the_headline_before_anything_visible():
    html = render([important([entry()])], total=5).html
    hidden = re.search(r'<div style="display:none[^"]*">([^<]*)</div>', html)
    assert hidden and "1 important" in hidden.group(1)
    assert html.index(hidden.group(0)) < html.index("<h1")


def test_three_big_number_tiles_show_emails_important_and_due_soon():
    html = render([important([entry(), entry("m2")]), due_table()], total=20).html
    for label in ("Emails", "Important", "Due soon"):
        assert f">{label}</div>" in html
    numbers = re.findall(r'font-size:28px[^"]*">(\d+)</div>', html)
    assert numbers == ["20", "2", "1"]


# ---- Round 3c: statements shown as a quiet list under the Money table ----


def statements_section(statements, rows=None):
    return SectionSummary(
        title="Money",
        mode="table",
        count=len(statements) + len(rows or []),
        table=TableData(
            columns=["What", "Who", "Amount", "When"],
            link_column=1,
            rows=rows or [],
            summary="1 statement",
            statements=statements,
        ),
    )


def test_statements_are_listed_with_a_link_under_a_statements_heading():
    ref = EmailRef(
        email_id="s1",
        sender="Example Bank <alerts@bank.example>",
        subject="Savings statement, Oct",
    )
    rendered = render([statements_section([ref])])
    for page in (rendered.html, rendered.text):
        assert "Statements" in page and "Savings statement, Oct" in page
        assert "alerts@bank.example" not in page and "Example Bank" in page
    assert 'href="https://mail.google.com/mail/u/0/#all/s1"' in rendered.html
    assert "#all/s1" in rendered.text


def test_no_statements_heading_when_there_are_none():
    rendered = render([table_section()])
    assert "Statements" not in rendered.html and "Statements" not in rendered.text


# ---- the profile's time zone decides every clock time and date shown ----


LATE_UNTIL = datetime(
    2026, 11, 8, 20, 0, tzinfo=UTC
)  # 1:30 AM on 9 Nov in India, 8 Nov in UTC


def render_in(zone):
    content = DigestContent(sections=[important([entry()])], other_count=0, total=1)
    return render_digest(content, SINCE, LATE_UNTIL, Profile(timezone=zone))


def test_the_window_and_subject_use_the_profiles_time_zone():
    india = render_in("Asia/Kolkata")
    assert "9 Nov" in india.subject and "1:30 AM" in india.text
    utc = render_in("UTC")
    assert "8 Nov" in utc.subject and "8:00 PM" in utc.text


def test_without_a_profile_times_are_shown_in_utc():
    content = DigestContent(sections=[important([entry()])], other_count=0, total=1)
    rendered = render_digest(content, SINCE, LATE_UNTIL)
    assert "8:00 PM" in rendered.text and "8 Nov" in rendered.subject


def test_the_other_mail_line_names_the_categories_no_section_covers():
    content = DigestContent(
        sections=[important([entry()])],
        other_count=3,
        total=4,
        other_categories=["newsletters", "statements"],
    )
    rendered = render_digest(content, SINCE, UNTIL)
    for page in (rendered.html, rendered.text):
        assert "Plus 3 other emails (newsletters, statements) not summarised" in page


def test_hidden_statements_are_counted_in_a_more_line():
    ref = EmailRef(email_id="s1", sender="Bank <b@x.com>", subject="Statement")
    section = statements_section([ref])
    section.table.statements_omitted = 4
    rendered = render([section])
    assert (
        "+4 more statements" in rendered.html and "+4 more statements" in rendered.text
    )


def test_a_huge_statements_list_is_shrunk_below_the_gmail_limit():
    refs = [
        EmailRef(
            email_id=f"s{i}",
            sender="Bank <b@x.com>",
            subject=f"Statement {i} " + "x" * 60,
        )
        for i in range(600)
    ]
    rendered = render([statements_section(refs)])
    assert len(rendered.html.encode()) < 100_000
    assert "more statements" in rendered.html
