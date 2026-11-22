"""The adapter between Azure's HTTP trigger and the approval page (agent/approval_web.py).

Checked before anything is built, in this order:
- CLEANUP_ENABLED must be "true": otherwise the page is simply not there (a kill switch).
- CLEANUP_LINK_SECRET and MONGODB_URI must be set. Without the database a click could never find
  the paused run, so this is a clear "not configured" error, never a silent in-memory fallback.
Unexpected errors give a generic page; the log names the error type only, never its message (an
error message once echoed a secret into the logs).
"""

import logging
from collections.abc import Callable, Mapping
from datetime import datetime
from urllib.parse import parse_qs

from agent.approval_web import WebResponse, _message, handle_cleanup_request

log = logging.getLogger("gmail_agent.cleanup")


def _setting(env: Mapping[str, str], name: str) -> str:
    return (env.get(name) or "").strip()


def serve(
    method: str,
    query: Mapping[str, str],
    body: bytes,
    env: Mapping[str, str],
    now: datetime,
    build_graph: Callable[[Mapping[str, str]], object],
) -> WebResponse:
    if _setting(env, "CLEANUP_ENABLED").lower() != "true":
        return _message(404, "Clean-up is not enabled.")
    secret = _setting(env, "CLEANUP_LINK_SECRET")
    if not secret or not _setting(env, "MONGODB_URI"):
        return _message(503, "Clean-up is not configured yet. Nothing was changed.")
    try:
        form = (
            parse_qs(body.decode("utf-8", errors="replace")) if method == "POST" else {}
        )
        response = handle_cleanup_request(
            method, query, form, now, secret, build_graph(env)
        )
    except Exception as error:  # noqa: BLE001 - the page must fail closed, without details
        log.warning("clean-up page failed: %s", type(error).__name__)
        return _message(500, "Something went wrong. Nothing was changed.")
    log.info("clean-up page %s -> %d", method, response.status)
    return response
