"""Run a model chain over many items, several items per request, a few requests at a time.

Shared by classification and summarisation. Two failure cases are handled here, once:
- Azure's content filter can reject a whole request because ONE item tripped it. That batch is
  retried one item at a time, and an item still rejected on its own gets `on_blocked(item)`.
- Any other error (e.g. a rate limit that outlasted the client's retries) is raised, not hidden.
"""

from collections.abc import Callable
from typing import Any

import openai
from langchain_core.runnables import Runnable


def is_content_filter_error(error: BaseException) -> bool:
    """Azure rejects a request whose text trips its content filter: HTTP 400, code content_filter."""
    return (
        isinstance(error, openai.BadRequestError)
        and getattr(error, "code", None) == "content_filter"
    )


def run_in_batches[T, R](
    items: list[T],
    chain: Runnable,
    *,
    make_request: Callable[[list[T]], dict[str, Any]],
    from_reply: Callable[[list[T], Any], list[R]],
    on_blocked: Callable[[T], R],
    batch_size: int,
    max_concurrency: int,
) -> list[R]:
    """One result per item, in order.

    `make_request(chunk)` builds the chain input for a chunk; `from_reply(chunk, reply)` turns the
    chain's reply into one result per item of that chunk. `chain.batch` is LangChain's built-in
    parallel runner; `max_concurrency` caps how many requests run at once.
    """
    if not items:
        return []
    config = {"max_concurrency": max_concurrency}
    chunks = [items[i : i + batch_size] for i in range(0, len(items), batch_size)]
    replies = chain.batch(
        [make_request(chunk) for chunk in chunks], config=config, return_exceptions=True
    )

    results: list[R] = []
    for chunk, reply in zip(chunks, replies, strict=True):
        if not isinstance(reply, BaseException):
            results.extend(from_reply(chunk, reply))
            continue
        if not is_content_filter_error(reply):
            raise reply
        singles = chain.batch(
            [make_request([item]) for item in chunk],
            config=config,
            return_exceptions=True,
        )
        for item, single in zip(chunk, singles, strict=True):
            if not isinstance(single, BaseException):
                results.extend(from_reply([item], single))
            elif is_content_filter_error(single):
                results.append(on_blocked(item))
            else:
                raise single
    return results
