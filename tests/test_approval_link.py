"""Signed approval links: the digest's button carries the thread id, an expiry and an HMAC signature.
Only a link this app signed, unchanged and unexpired, opens a clean-up."""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from agent.approval_link import LINK_HOURS, make_link, verify

SECRET = "test-secret-not-real"
NOW = datetime(2026, 11, 22, 0, 30, tzinfo=UTC)
BASE = "https://example.invalid"


def params_of(link):
    return {k: v[0] for k, v in parse_qs(urlsplit(link).query).items()}


def test_a_link_this_app_signed_opens_its_thread():
    link = make_link(BASE, "2026-11-22-ab12", NOW, SECRET)
    assert link.startswith(f"{BASE}/api/cleanup?")
    assert (
        verify(params_of(link), NOW + timedelta(hours=1), SECRET) == "2026-11-22-ab12"
    )


def test_the_link_lasts_48_hours():
    assert LINK_HOURS == 48
    params = params_of(make_link(BASE, "t1", NOW, SECRET))
    assert verify(params, NOW + timedelta(hours=47, minutes=59), SECRET) == "t1"
    assert verify(params, NOW + timedelta(hours=48, seconds=1), SECRET) is None


@pytest.mark.parametrize(
    "change",
    [
        {"t": "someone-elses-thread"},
        {"e": "9999999999"},  # a later expiry
        {"s": "0" * 64},
    ],
)
def test_any_change_to_the_link_is_rejected(change):
    params = {**params_of(make_link(BASE, "t1", NOW, SECRET)), **change}
    assert verify(params, NOW, SECRET) is None


def test_a_link_signed_with_another_secret_is_rejected():
    params = params_of(make_link(BASE, "t1", NOW, "other-secret"))
    assert verify(params, NOW, SECRET) is None


@pytest.mark.parametrize(
    "params", [{}, {"t": "t1"}, {"t": "t1", "e": "soon", "s": "x"}]
)
def test_missing_or_malformed_parts_are_rejected(params):
    assert verify(params, NOW, SECRET) is None


def test_an_empty_secret_never_signs_or_verifies():
    with pytest.raises(ValueError):
        make_link(BASE, "t1", NOW, "")
    params = params_of(make_link(BASE, "t1", NOW, SECRET))
    assert verify(params, NOW, "") is None
