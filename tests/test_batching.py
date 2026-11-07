import httpx
import openai
import pytest
from langchain_core.runnables import RunnableLambda

from agent.batching import is_content_filter_error, run_in_batches


def bad_request(code):
    response = httpx.Response(
        400, request=httpx.Request("POST", "https://example.invalid/")
    )
    return openai.BadRequestError(
        "rejected", response=response, body={"code": code, "message": "rejected"}
    )


def shout(request):
    """A model that upper-cases every item in the request, rejecting the word 'bad'."""
    if "bad" in request["items"]:
        raise bad_request("content_filter")
    return [item.upper() for item in request["items"]]


def run(items, chain, **kwargs):
    return run_in_batches(
        items,
        chain,
        make_request=lambda chunk: {"items": list(chunk)},
        from_reply=lambda chunk, reply: list(reply),
        on_blocked=lambda item: f"BLOCKED:{item}",
        **{"batch_size": 2, "max_concurrency": 2, **kwargs},
    )


def test_results_come_back_in_order_across_several_requests():
    assert run(list("abcde"), RunnableLambda(shout)) == list("ABCDE")


def test_each_request_carries_at_most_batch_size_items():
    sizes = []

    def record(request):
        sizes.append(len(request["items"]))
        return shout(request)

    run(list("abcde"), RunnableLambda(record), batch_size=2)
    assert sorted(sizes) == [1, 2, 2]


def test_no_items_means_the_chain_is_never_called():
    class Exploding:
        def batch(self, *_a, **_k):
            raise AssertionError("must not be called")

    assert run([], Exploding()) == []


def test_the_concurrency_cap_is_passed_to_the_chain():
    seen = {}

    class Recording:
        def batch(self, inputs, config=None, **_kwargs):
            seen["config"] = config
            return [[x.upper() for x in request["items"]] for request in inputs]

    run(["a"], Recording(), max_concurrency=3)
    assert seen["config"] == {"max_concurrency": 3}


def test_a_content_filter_rejection_retries_that_batch_one_item_at_a_time():
    result = run(["a", "bad", "c", "d", "e"], RunnableLambda(shout), batch_size=2)
    assert result == ["A", "BLOCKED:bad", "C", "D", "E"]


def test_other_errors_are_raised_not_hidden():
    def boom(_request):
        raise RuntimeError("rate limit exhausted")

    with pytest.raises(RuntimeError, match="rate limit exhausted"):
        run(["a"], RunnableLambda(boom))


def test_a_400_that_is_not_a_content_filter_is_raised():
    def other(_request):
        raise bad_request("invalid_request_error")

    with pytest.raises(openai.BadRequestError):
        run(["a"], RunnableLambda(other))


def test_only_a_content_filter_400_counts_as_a_content_filter_error():
    assert is_content_filter_error(bad_request("content_filter"))
    assert not is_content_filter_error(bad_request("other"))
    assert not is_content_filter_error(RuntimeError("x"))
