"""The daily job and the clean-up: with CLEANUP_ENABLED on (and a real run), the digest carries a
signed "Review and choose" link, and right after it is sent an approval thread is started with
the same id. Anything missing or failing never costs the digest itself."""

import logging
from urllib.parse import parse_qs, urlsplit

import pytest
from test_daily import EMAILS, email
from test_job import NOW, RecordingGmail, make_deps

from agent.approval_link import verify
from agent.job import JobFailedError, run_scheduled

SECRET = "test-secret-not-real"
BASE = "https://app.example.invalid"
ON = {
    "DRY_RUN": "false",
    "CLEANUP_ENABLED": "true",
    "CLEANUP_LINK_SECRET": SECRET,
    "CLEANUP_BASE_URL": BASE,
}
WITH_PROMO = [*EMAILS, email("5", "Sale ends tonight"), email("6", "Sale: 2 for 1")]


class Starter:
    def __init__(self, fail=False):
        self.calls = []
        self._fail = fail

    def __call__(self, thread_id, cleanup):
        if self._fail:
            raise RuntimeError("database down: mongodb+srv://user:pass@host")
        self.calls.append((thread_id, cleanup))


def go(env, emails=WITH_PROMO, starter=None, fail_send=False):
    gmail = RecordingGmail(emails)
    gmail.fail_send = fail_send
    deps = make_deps(gmail=gmail)
    deps.start_approval = starter if starter is not None else Starter()
    try:
        result = run_scheduled(env, NOW, lambda _env: deps)
    except JobFailedError as error:
        return None, deps, error
    return result, deps, None


def sent_html(deps):
    ((_, _, html),) = deps.gmail.sent
    return html


def review_link(html):
    links = [
        h
        for h in __import__("re").findall(r'href="([^"]+)"', html)
        if "/api/cleanup" in h
    ]
    assert len(links) == 1
    return links[0].replace("&amp;", "&")


def test_the_digest_links_to_the_page_and_the_same_thread_is_started_after_sending():
    _, deps, _ = go(ON)
    link = review_link(sent_html(deps))
    assert link.startswith(f"{BASE}/api/cleanup?")
    params = {k: v[0] for k, v in parse_qs(urlsplit(link).query).items()}
    thread_from_link = verify(params, NOW, SECRET)
    ((thread_id, cleanup),) = deps.start_approval.calls
    assert thread_id == thread_from_link
    assert cleanup.email_ids == ["5", "6"]


def test_each_run_gets_a_new_thread_id_starting_with_the_date():
    _, first, _ = go(ON)
    _, second, _ = go(ON)
    a, b = first.start_approval.calls[0][0], second.start_approval.calls[0][0]
    assert a != b and a.startswith("2026-11-09")


def test_with_the_switch_off_there_is_no_clean_up_at_all():
    for env in ({"DRY_RUN": "false"}, {**ON, "CLEANUP_ENABLED": "false"}):
        _, deps, _ = go(env)
        assert deps.start_approval.calls == []
        assert "Clean-up" not in sent_html(deps)


def test_a_dry_run_never_offers_a_clean_up():
    _, deps, _ = go({**ON, "DRY_RUN": "true"})
    assert deps.start_approval.calls == [] and deps.gmail.sent == []


def test_no_promotions_means_no_thread_and_no_button():
    _, deps, _ = go(ON, emails=EMAILS)
    assert deps.start_approval.calls == []
    assert "/api/cleanup" not in sent_html(deps)


@pytest.mark.parametrize("missing", ["CLEANUP_LINK_SECRET", "CLEANUP_BASE_URL"])
def test_missing_link_settings_skip_the_clean_up_but_still_send_the_digest(
    missing, caplog
):
    with caplog.at_level(logging.WARNING, logger="gmail_agent.job"):
        _, deps, error = go({**ON, missing: " "})
    assert error is None and len(deps.gmail.sent) == 1
    assert deps.start_approval.calls == []
    assert "/api/cleanup" not in sent_html(deps)
    assert "clean-up" in caplog.text.lower()


def test_if_the_digest_was_not_sent_no_thread_is_started():
    _, deps, error = go(ON, fail_send=True)
    assert error is not None
    assert deps.start_approval.calls == []


def test_a_failure_to_start_the_thread_fails_the_run_without_leaking_its_text():
    _, deps, error = go(ON, starter=Starter(fail=True))
    assert len(deps.gmail.sent) == 1  # the digest still went out
    assert "start_approval: RuntimeError" in str(error)
    assert "mongodb" not in str(error)
