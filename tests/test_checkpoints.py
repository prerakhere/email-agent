"""Where paused approval threads are saved: MongoDB (Azure DocumentDB) when MONGODB_URI is set,
in memory otherwise (tests, local dry runs)."""

from unittest.mock import MagicMock

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.mongodb import MongoDBSaver

from agent.checkpoints import CHECKPOINT_DB, CHECKPOINT_TTL_SECONDS, build_checkpointer


def test_without_a_database_setting_checkpoints_stay_in_memory():
    assert isinstance(build_checkpointer({}), InMemorySaver)
    assert isinstance(build_checkpointer({"MONGODB_URI": "  \n"}), InMemorySaver)


def test_with_a_database_setting_checkpoints_go_to_mongodb_and_expire():
    made = {}

    def client_factory(uri, **kwargs):
        made["uri"], made["kwargs"] = uri, kwargs
        made["client"] = MagicMock()
        return made["client"]

    saver = build_checkpointer(
        {"MONGODB_URI": " mongodb+srv://example.invalid/ \n"},
        client_factory=client_factory,
    )
    assert isinstance(saver, MongoDBSaver)
    assert (
        made["uri"] == "mongodb+srv://example.invalid/"
    )  # stripped: a stray newline once broke a key
    assert (
        made["kwargs"]["serverSelectionTimeoutMS"] > 0
    )  # fail fast instead of hanging the run
    assert saver.ttl == CHECKPOINT_TTL_SECONDS
    assert CHECKPOINT_TTL_SECONDS >= 48 * 3600  # outlives the approval link
    made["client"].__getitem__.assert_any_call(CHECKPOINT_DB)


def test_saved_clean_up_items_come_back_as_allowed_types_without_a_warning(caplog):
    from agent.approval import build_approval_graph, pending_items, start_approval
    from agent.cleanup import CleanupItem, CleanupList

    class NoGmail:
        def trash(self, email_id):
            raise AssertionError("never called")

    graph = build_approval_graph(NoGmail(), build_checkpointer({}))
    item = CleanupItem(
        email_id="1", sender="S <s@x.example>", subject="Offer", summary="s"
    )
    start_approval(graph, "t1", CleanupList(items=[item]))
    with caplog.at_level("WARNING"):
        found = pending_items(graph, "t1")
    assert found == [item] and isinstance(found[0], CleanupItem)
    assert "unregistered type" not in caplog.text
