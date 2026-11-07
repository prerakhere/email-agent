import pytest

from agent.llm import MAX_OUTPUT_TOKENS, MAX_RETRIES, REQUIRED, build_llm

ENV = {
    "AZURE_OPENAI_ENDPOINT": "https://example.cognitiveservices.azure.com/",
    "AZURE_OPENAI_API_KEY": "not-a-real-key",
    "AZURE_OPENAI_API_VERSION": "2025-01-01-preview",
    "AZURE_OPENAI_DEPLOYMENT": "gpt-4.1-mini",
}


def test_the_client_retries_rate_limits_instead_of_failing_fast():
    llm = build_llm(ENV)
    assert llm.max_retries == MAX_RETRIES
    assert MAX_RETRIES >= 6  # a burst of parallel calls needs more than the default 2


def test_the_client_is_deterministic():
    assert build_llm(ENV).temperature == 0


def test_missing_settings_are_named_in_the_error():
    env = {k: v for k, v in ENV.items() if k != "AZURE_OPENAI_API_KEY"}
    with pytest.raises(ValueError, match="AZURE_OPENAI_API_KEY"):
        build_llm(env)


def test_required_settings_are_the_four_azure_variables():
    assert sorted(REQUIRED) == sorted(ENV)


def test_replies_are_capped_so_each_call_reserves_little_of_the_token_quota():
    llm = build_llm(ENV)
    assert llm.max_tokens == MAX_OUTPUT_TOKENS
    assert (
        1000 <= MAX_OUTPUT_TOKENS <= 2000
    )  # ten short answers fit; far below the default
