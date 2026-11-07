"""One place that builds the Azure OpenAI chat client, shared by the scripts.

max_retries is raised well above the library default (2): classifying many emails in parallel
bursts past the deployment's request-rate limit, and the OpenAI client then waits (honouring the
server's retry hint) and tries again instead of crashing the whole run with a 429.

max_tokens caps the reply. Azure estimates each request's token cost up front, partly from this
cap, so an unset cap can make every call count as far bigger than its real size and exhaust the
tokens-per-minute quota early. A reply is one short JSON object per email (ten per request),
so a modest cap is plenty.
"""

import os
from collections.abc import Mapping

from langchain_openai import AzureChatOpenAI

REQUIRED = [
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_API_VERSION",
    "AZURE_OPENAI_DEPLOYMENT",
]
MAX_RETRIES = 8
MAX_OUTPUT_TOKENS = (
    1500  # room for ten short answers, yet far below the default reservation
)


def build_llm(env: Mapping[str, str] = os.environ) -> AzureChatOpenAI:
    missing = [name for name in REQUIRED if not env.get(name)]
    if missing:
        raise ValueError(f"Missing settings: {', '.join(missing)}")
    return AzureChatOpenAI(
        azure_endpoint=env["AZURE_OPENAI_ENDPOINT"],
        api_key=env["AZURE_OPENAI_API_KEY"],
        api_version=env["AZURE_OPENAI_API_VERSION"],
        azure_deployment=env["AZURE_OPENAI_DEPLOYMENT"],
        temperature=0,
        max_retries=MAX_RETRIES,
        max_tokens=MAX_OUTPUT_TOKENS,
    )
