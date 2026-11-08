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
    # Values are stripped: a stray newline in a secret once became an illegal HTTP header value and
    # made every model call fail (and the library's error text then echoed the key into the logs).
    values = {name: env.get(name, "").strip() for name in REQUIRED}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ValueError(f"Missing settings: {', '.join(missing)}")
    return AzureChatOpenAI(
        azure_endpoint=values["AZURE_OPENAI_ENDPOINT"],
        api_key=values["AZURE_OPENAI_API_KEY"],
        api_version=values["AZURE_OPENAI_API_VERSION"],
        azure_deployment=values["AZURE_OPENAI_DEPLOYMENT"],
        temperature=0,
        max_retries=MAX_RETRIES,
        max_tokens=MAX_OUTPUT_TOKENS,
    )
