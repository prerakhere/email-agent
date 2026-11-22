"""The adapter between Azure's HTTP trigger and the approval page: the kill switch, required
settings, form parsing, and errors that never leak their message."""

import logging
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlencode, urlsplit

from agent.approval import build_approval_graph, start_approval
from agent.approval_http import serve
from agent.approval_link import make_link
from agent.checkpoints import build_checkpointer
from agent.cleanup import CleanupItem, CleanupList

NOW = datetime(2026, 11, 22, 0, 30, tzinfo=UTC)
ENV = {
    "CLEANUP_ENABLED": "true",
    "CLEANUP_LINK_SECRET": "test-secret-not-real",
    "MONGODB_URI": "mongodb+srv://example.invalid/",
}


class FakeGmail:
    def __init__(self):
        self.trashed: list[str] = []

    def trash(self, email_id):
        self.trashed.append(email_id)


def ready():
    gmail = FakeGmail()
    graph = build_approval_graph(gmail, build_checkpointer({}))
    items = [
        CleanupItem(
            email_id=m, sender="S <s@x.example>", subject=f"Offer {m}", summary="s"
        )
        for m in ("1", "2", "3")
    ]
    start_approval(graph, "t1", CleanupList(items=items))
    link = make_link("https://x.invalid", "t1", NOW, ENV["CLEANUP_LINK_SECRET"])
    params = {k: v[0] for k, v in parse_qs(urlsplit(link).query).items()}
    built = []

    def build(env):
        built.append(env)
        return graph

    return gmail, params, build, built


def test_a_get_shows_the_list():
    _, params, build, _ = ready()
    page = serve("GET", params, b"", ENV, NOW, build)
    assert page.status == 200 and "Offer 2" in page.body


def test_a_posted_form_with_repeated_ids_bins_those():
    gmail, params, build, _ = ready()
    body = urlencode(
        [*params.items(), ("action", "bin"), ("id", "1"), ("id", "3")]
    ).encode()
    page = serve("POST", {}, body, ENV, NOW, build)
    assert gmail.trashed == ["1", "3"]
    assert "Moved 2 emails" in page.body


def test_with_the_switch_off_nothing_is_built_or_done():
    gmail, params, build, built = ready()
    for value in (None, "false", "yes"):
        env = (
            {**ENV, "CLEANUP_ENABLED": value}
            if value
            else {k: v for k, v in ENV.items() if k != "CLEANUP_ENABLED"}
        )
        page = serve(
            "POST",
            {},
            urlencode([*params.items(), ("action", "bin"), ("id", "1")]).encode(),
            env,
            NOW,
            build,
        )
        assert page.status == 404
    assert built == [] and gmail.trashed == []


def test_the_switch_ignores_case_and_spaces():
    _, params, build, _ = ready()
    assert (
        serve(
            "GET", params, b"", {**ENV, "CLEANUP_ENABLED": " True \n"}, NOW, build
        ).status
        == 200
    )


def test_missing_secret_or_database_is_a_clear_error_and_never_falls_back_to_memory():
    _, params, build, built = ready()
    for missing in ("CLEANUP_LINK_SECRET", "MONGODB_URI"):
        env = {**ENV, missing: "  "}
        page = serve("GET", params, b"", env, NOW, build)
        assert page.status == 503
        assert "not configured" in page.body.lower()
    assert built == []


def test_an_unexpected_error_shows_a_generic_page_and_logs_only_its_type(caplog):
    _, params, _, _ = ready()

    def broken(env):
        raise RuntimeError("secret detail: mongodb+srv://user:pass@host")

    with caplog.at_level(logging.WARNING):
        page = serve("GET", params, b"", ENV, NOW, broken)
    assert page.status == 500
    assert "secret detail" not in page.body and "secret detail" not in caplog.text
    assert "RuntimeError" in caplog.text
    assert page.headers["Cache-Control"] == "no-store"
