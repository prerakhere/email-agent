"""The approval page: GET shows the list (every email ticked, a Select all box, two buttons); only
the form's POST acts. Both check the signed link first."""

import re
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

from langgraph.checkpoint.memory import InMemorySaver

from agent.approval import build_approval_graph, pending_items, start_approval
from agent.approval_link import make_link
from agent.approval_web import handle_cleanup_request
from agent.cleanup import CleanupItem, CleanupList

SECRET = "test-secret-not-real"
NOW = datetime(2026, 11, 22, 0, 30, tzinfo=UTC)
THREAD = "2026-11-22-ab12"


class FakeGmail:
    def __init__(self):
        self.trashed: list[str] = []

    def trash(self, email_id):
        self.trashed.append(email_id)


def item(mid, subject=None, summary="20% off shoes until Sunday."):
    return CleanupItem(
        email_id=mid,
        sender=f"Shop {mid} <deals@shop{mid}.example>",
        subject=subject or f"Offer {mid}",
        summary=summary,
    )


def setup(items=None):
    gmail = FakeGmail()
    graph = build_approval_graph(gmail, InMemorySaver())
    start_approval(
        graph, THREAD, CleanupList(items=items or [item("1"), item("2"), item("3")])
    )
    params = {
        k: v[0]
        for k, v in parse_qs(
            urlsplit(make_link("https://x.invalid", THREAD, NOW, SECRET)).query
        ).items()
    }
    return graph, gmail, params


def get(graph, params, now=NOW):
    return handle_cleanup_request("GET", params, {}, now, SECRET, graph)


def post(graph, params, action, ids=(), now=NOW):
    form = {k: [v] for k, v in params.items()} | {"action": [action], "id": list(ids)}
    return handle_cleanup_request("POST", {}, form, now, SECRET, graph)


def test_the_page_lists_every_email_with_sender_subject_and_summary():
    graph, _, params = setup()
    page = get(graph, params)
    assert page.status == 200
    for mid in ("1", "2", "3"):
        assert f"Offer {mid}" in page.body
        assert f"Shop {mid}" in page.body
    assert page.body.count("20% off shoes until Sunday.") == 3


def test_every_email_starts_ticked_and_there_is_a_select_all_box():
    graph, _, params = setup()
    page = get(graph, params)
    boxes = re.findall(
        r'<input type="checkbox" name="id" value="([^"]+)" class="item" checked>',
        page.body,
    )
    assert boxes == ["1", "2", "3"]
    assert 'id="select-all"' in page.body and "checked" in page.body


def test_the_page_has_the_two_buttons_and_carries_the_signed_link_in_the_form():
    graph, _, params = setup()
    body = get(graph, params).body
    assert '<form method="post"' in body
    assert 'name="action" value="bin"' in body and "Move selected to Bin" in body
    assert 'name="action" value="keep"' in body and "Keep all" in body
    for key in ("t", "e", "s"):
        assert f'name="{key}" value="{params[key]}"' in body


def test_each_email_can_be_opened_in_gmail():
    graph, _, params = setup()
    assert "mail.google.com" in get(graph, params).body


def test_opening_the_page_changes_nothing():
    graph, gmail, params = setup()
    get(graph, params)
    get(graph, params)
    assert gmail.trashed == []
    assert pending_items(graph, THREAD) is not None


def test_email_text_is_escaped():
    graph, _, params = setup(
        [item("1", subject="<script>alert(1)</script>", summary='"><img src=x>')]
    )
    body = get(graph, params).body
    assert "<script>alert(1)</script>" not in body and "<img src=x>" not in body
    assert "&lt;script&gt;" in body


def test_a_bad_or_expired_link_shows_no_list():
    graph, _, params = setup()
    for page in (
        get(graph, {**params, "s": "0" * 64}),
        get(graph, params, now=NOW + timedelta(hours=49)),
    ):
        assert page.status == 403
        assert "Offer 1" not in page.body


def test_an_answered_thread_says_nothing_is_waiting():
    graph, _, params = setup()
    post(graph, params, "keep")
    page = get(graph, params)
    assert page.status == 410
    assert "Offer 1" not in page.body


def test_move_selected_bins_only_the_ticked_emails():
    graph, gmail, params = setup()
    page = post(graph, params, "bin", ["1", "3"])
    assert gmail.trashed == ["1", "3"]
    assert page.status == 200
    assert "Moved 2 emails to the Bin" in page.body
    assert "30 days" in page.body


def test_keep_all_bins_nothing_even_if_boxes_were_ticked():
    graph, gmail, params = setup()
    page = post(graph, params, "keep", ["1", "2"])
    assert gmail.trashed == []
    assert "Kept all" in page.body


def test_moving_with_nothing_ticked_keeps_everything():
    graph, gmail, params = setup()
    page = post(graph, params, "bin", [])
    assert gmail.trashed == []
    assert "Kept all" in page.body


def test_a_post_with_a_bad_signature_does_nothing():
    graph, gmail, params = setup()
    page = post(graph, {**params, "s": "0" * 64}, "bin", ["1"])
    assert page.status == 403
    assert gmail.trashed == []
    assert pending_items(graph, THREAD) is not None


def test_a_second_submit_does_nothing():
    graph, gmail, params = setup()
    post(graph, params, "bin", ["1"])
    page = post(graph, params, "bin", ["2"])
    assert page.status == 410
    assert gmail.trashed == ["1"]


def test_an_unknown_action_or_method_does_nothing():
    graph, gmail, params = setup()
    assert post(graph, params, "delete-everything", ["1"]).status == 400
    assert handle_cleanup_request("PUT", params, {}, NOW, SECRET, graph).status == 405
    assert gmail.trashed == []


def test_every_page_is_private_uncached_and_not_embeddable():
    graph, _, params = setup()
    for page in (get(graph, params), get(graph, {}), post(graph, params, "keep")):
        assert page.headers["Cache-Control"] == "no-store"
        assert page.headers["Referrer-Policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]
        assert page.headers["Content-Type"].startswith("text/html")
