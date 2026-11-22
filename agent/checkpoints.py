"""Where paused approval threads are saved between the daily run and the owner's click.

With MONGODB_URI set (production: Azure DocumentDB, the MongoDB-compatible service, read from Key
Vault), LangGraph's official MongoDB checkpointer is used. Without it, an in-memory saver: right for
tests and local dry runs, useless across processes, so production must set the URI.

Checkpoints expire on their own through a MongoDB TTL index a little after the approval link does,
and an answered thread is deleted at once (agent/approval.py), so the store never piles up.
"""

import os
from collections.abc import Callable, Mapping

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pymongo import MongoClient

CHECKPOINT_DB = "email_agent"
CHECKPOINT_TTL_SECONDS = (
    3 * 24 * 3600
)  # the approval link lasts 48 hours; keep a margin
SERVER_TIMEOUT_MS = (
    10_000  # fail fast if the database is unreachable instead of hanging the run
)
# The only custom type a checkpoint may rebuild. LangGraph is moving to refuse unlisted types, so a
# tampered store can't make the app construct arbitrary objects; listing ours keeps resume working.
ALLOWED_TYPES = [("agent.cleanup", "CleanupItem")]


def _serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=ALLOWED_TYPES)


def build_checkpointer(
    env: Mapping[str, str] = os.environ,
    client_factory: Callable[..., MongoClient] = MongoClient,
) -> BaseCheckpointSaver:
    uri = env.get(
        "MONGODB_URI", ""
    ).strip()  # stripped: a stray newline once broke a secret
    if not uri:
        return InMemorySaver(serde=_serializer())
    # Imported here so tests and local runs without a database never load the Mongo stack.
    from langgraph.checkpoint.mongodb import MongoDBSaver

    client = client_factory(uri, serverSelectionTimeoutMS=SERVER_TIMEOUT_MS)
    return MongoDBSaver(
        client, db_name=CHECKPOINT_DB, ttl=CHECKPOINT_TTL_SECONDS, serde=_serializer()
    )
