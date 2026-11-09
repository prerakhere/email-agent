"""Guard rails for how the digest behaves in real mail clients (Gmail, Outlook, phones).

Mail clients strip or ignore much of modern HTML, so these tests keep the email inside the safe
subset: table layout, inline styles, no scripts, no external files, narrow width, links only to
Gmail. They check structure; the final look still needs a real send to Gmail.
"""

import re
from datetime import UTC, datetime

from agent.digest import DigestContent, EmailRef, SectionSummary
from agent.digest_email import render_digest
from agent.digest_tables import TableData, TableRow
from agent.nodes.summarize import EmailSummary, GroupSummary

SINCE = datetime(2026, 11, 8, 2, 30, tzinfo=UTC)
UNTIL = datetime(2026, 11, 9, 2, 30, tzinfo=UTC)


def full_digest():
    important = SectionSummary(
        title="Important",
        mode="per_email",
        count=1,
        items=[
            EmailSummary(
                email_id="a1",
                sender="Jane <jane@corp.com>",
                subject="Interview",
                summary="They want Tuesday.",
                action_points=["Reply"],
            )
        ],
    )
    bills = SectionSummary(
        title="Bills and receipts",
        mode="table",
        count=1,
        table=TableData(
            columns=["Type", "Biller", "Amount", "Due"],
            link_column=1,
            rows=[
                TableRow(
                    email_id="b1",
                    cells=["bill", "Bank", "₹100.00", "tomorrow"],
                    highlight=True,
                )
            ],
            summary="1 bill: ₹100.00",
        ),
    )
    group = SectionSummary(
        title="Notifications",
        mode="group",
        count=2,
        group=GroupSummary(count=2, summary="Two pings."),
        refs=[EmailRef(email_id="g1", sender="App <a@x.com>", subject="Ping")],
    )
    return DigestContent(sections=[important, bills, group], other_count=1, total=5)


def html():
    return render_digest(full_digest(), SINCE, UNTIL).html


def test_no_style_blocks_scripts_or_external_files():
    page = html().lower()
    for banned in ("<style", "<script", "<link", "<img", "@import", "url(", "<iframe"):
        assert banned not in page, banned


def test_no_layout_features_that_mail_clients_ignore():
    page = html().lower()
    for banned in ("display:flex", "display:grid", "position:", "float:", "calc("):
        assert banned not in page, banned


def test_every_link_goes_to_gmail():
    hrefs = re.findall(r'href="([^"]+)"', html())
    assert hrefs and all(h.startswith("https://mail.google.com/") for h in hrefs)


def test_the_layout_is_no_wider_than_600_pixels():
    widths = [int(w) for w in re.findall(r"max-width:\s*(\d+)px", html())]
    assert widths and max(widths) <= 600


def test_the_text_version_has_no_markup_and_every_item_has_its_link():
    text = render_digest(full_digest(), SINCE, UNTIL).text
    assert not re.search(r"<[a-z/][^>]*>", text)
    for mail_id in ("a1", "b1", "g1"):
        assert f"#all/{mail_id}" in text


def test_a_normal_digest_is_far_below_the_gmail_clip_limit():
    assert len(html().encode()) < 20_000


# ---- Round 2: layout and colours that survive light and dark mode ----


def test_the_email_is_a_full_document_that_declares_light_and_dark_support():
    page = html()
    assert page.lower().startswith("<!doctype html>")
    assert '<meta name="color-scheme" content="light dark">' in page
    assert '<meta name="viewport"' in page and "<title>" in page


def test_no_background_is_hard_coded_so_the_client_can_choose_light_or_dark():
    page = html().lower()
    assert not re.search(
        r"background(-color)?:\s*(#fff\b|#ffffff|#000\b|#000000|white|black)", page
    )
    assert "<body" in page and "background" not in page.split("<body")[1].split(">")[0]


def test_text_colours_are_mid_tones_that_stay_readable_on_either_background():
    def luminance(hex6):
        r, g, b = (int(hex6[i : i + 2], 16) / 255 for i in (0, 2, 4))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    colours = re.findall(r"[^-]color:\s*#([0-9a-fA-F]{6})", html())
    assert colours
    for value in colours:
        if value.lower() == "ffffff":  # only the letter inside a coloured avatar circle
            continue
        assert 0.15 <= luminance(value) <= 0.85, value


def test_every_section_heading_has_a_coloured_rule():
    page = html()
    assert len(re.findall(r"border-bottom:\s*2px solid #[0-9a-fA-F]{6}", page)) >= 3


def test_sections_get_different_colours_in_a_fixed_order():
    rules = re.findall(r"border-bottom:\s*2px solid (#[0-9a-fA-F]{6})", html())
    assert len(set(rules[:3])) == 3
    assert rules == re.findall(r"border-bottom:\s*2px solid (#[0-9a-fA-F]{6})", html())


def test_each_mail_row_has_a_text_initial_avatar_not_an_image():
    page = html()
    assert re.search(r'border-radius:\s*16px[^"]*">J</div>', page)  # Jane
    assert "<img" not in page


def test_rows_are_tall_enough_to_tap_on_a_phone():
    page = html()
    paddings = [int(p) for p in re.findall(r"padding:\s*(\d+)px \d+px \d+px", page)]
    assert paddings and max(paddings) >= 12
