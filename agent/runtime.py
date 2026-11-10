"""Build everything a run needs from settings (environment variables) and the app folder.

Used by the Azure Function; the local scripts build their own pieces the same way. The Azure OpenAI
settings are checked first so a mistake fails fast, before any call to Google.

Files read from the app folder (all optional): rules.json (learned sender rules), digest.toml
(the digest layout) and profile.toml (personal taste). They are deployed alongside the code but are NOT in git.
"""

from collections.abc import Mapping
from pathlib import Path

from googleapiclient.discovery import build

from agent.auth import refreshed_credentials
from agent.digest_config import load_digest_config
from agent.gmail_client import GmailClient
from agent.job import Dependencies
from agent.llm import build_llm
from agent.nodes.classify import build_classifier
from agent.nodes.extract import build_extractor
from agent.nodes.summarize import build_group_summarizer, build_summarizer
from agent.nodes.transactions import build_transaction_extractor
from agent.profile import load_profile
from agent.rules import load_rules
from agent.sheets_client import SheetsClient

APP_ROOT = Path(__file__).resolve().parent.parent


def build_dependencies(env: Mapping[str, str], root: Path = APP_ROOT) -> Dependencies:
    llm = build_llm(
        env
    )  # validates the Azure settings before anything touches the network
    creds = refreshed_credentials(env)
    # cache_discovery=False: a serverless host has no persistent file cache for Google's API docs.
    gmail = GmailClient(build("gmail", "v1", credentials=creds, cache_discovery=False))
    sheet_id = env.get("SHEET_ID")
    sheets = (
        SheetsClient(
            build("sheets", "v4", credentials=creds, cache_discovery=False), sheet_id
        )
        if sheet_id
        else None
    )
    return Dependencies(
        gmail=gmail,
        sheets=sheets,
        rules=load_rules(root / "rules.json"),
        config=load_digest_config(root / "digest.toml"),
        profile=load_profile(root / "profile.toml"),
        classifier=build_classifier(llm),
        extractor=build_extractor(llm),
        summarizer=build_summarizer(llm),
        group_summarizer=build_group_summarizer(llm),
        transaction_extractor=build_transaction_extractor(llm),
    )
