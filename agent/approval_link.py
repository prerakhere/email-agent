"""Signed approval links. The digest's button carries the thread id, an expiry time and an HMAC
signature over both, made with a secret only the app knows (Key Vault). Anyone can see the link,
but nobody can change the thread or extend the expiry without the secret.

An HMAC is a keyed fingerprint: the same secret and text always give the same signature, and without
the secret it can't be produced. Signatures are compared in constant time so they can't be guessed
one character at a time from response timings.
"""

import hashlib
import hmac
from collections.abc import Mapping
from datetime import datetime, timedelta
from urllib.parse import urlencode

LINK_HOURS = 48
PATH = "/api/cleanup"


def _signature(thread_id: str, expires: int, secret: str) -> str:
    message = f"{thread_id}|{expires}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def make_link(base_url: str, thread_id: str, now: datetime, secret: str) -> str:
    if not secret:
        raise ValueError("the approval link secret is not set")
    expires = int((now + timedelta(hours=LINK_HOURS)).timestamp())
    query = urlencode(
        {"t": thread_id, "e": expires, "s": _signature(thread_id, expires, secret)}
    )
    return f"{base_url.rstrip('/')}{PATH}?{query}"


def verify(params: Mapping[str, str], now: datetime, secret: str) -> str | None:
    """The thread id if the link is this app's, unchanged and unexpired; otherwise None."""
    thread_id, expires, signature = params.get("t"), params.get("e"), params.get("s")
    if not (secret and thread_id and expires and signature) or not expires.isdigit():
        return None
    expected = _signature(thread_id, int(expires), secret)
    if not hmac.compare_digest(expected, signature):
        return None
    if now.timestamp() > int(expires):
        return None
    return thread_id
