"""The approval graph: START -> approval (pauses with interrupt) -> bin -> END.

The daily run starts it after the digest is sent; it pauses at once and its state is checkpointed.
The owner's click resumes the same thread with the ticked email ids. Tests use LangGraph's
in-memory checkpointer; production will use a durable one."""

from langgraph.checkpoint.memory import InMemorySaver

from agent.approval import (
    build_approval_graph,
    pending_items,
    resume_approval,
    start_approval,
)
from agent.cleanup import CleanupItem, CleanupList


class FakeGmail:
    def __init__(self, fail=()):
        self.trashed: list[str] = []
        self._fail = set(fail)

    def trash(self, email_id):
        if email_id in self._fail:
            raise RuntimeError("gmail down: private text")
        self.trashed.append(email_id)


def item(mid):
    return CleanupItem(
        email_id=mid,
        sender=f"Shop <{mid}@shop.example>",
        subject=f"Offer {mid}",
        summary="s",
    )


CLEANUP = CleanupList(items=[item("1"), item("2"), item("3")])


def started(gmail=None, thread="2026-11-22", cleanup=CLEANUP):
    gmail = gmail or FakeGmail()
    graph = build_approval_graph(gmail, InMemorySaver())
    start_approval(graph, thread, cleanup)
    return graph, gmail


def test_starting_pauses_before_anything_is_binned():
    graph, gmail = started()
    assert gmail.trashed == []
    assert pending_items(graph, "2026-11-22") == CLEANUP.items


def test_resuming_with_ticked_ids_bins_exactly_those():
    graph, gmail = started()
    outcome = resume_approval(graph, "2026-11-22", ["1", "3"])
    assert gmail.trashed == ["1", "3"]
    assert outcome.status == "binned"
    assert outcome.binned == ["1", "3"]


def test_ids_that_were_not_on_the_list_are_ignored():
    graph, gmail = started()
    outcome = resume_approval(graph, "2026-11-22", ["2", "someone-elses-mail"])
    assert gmail.trashed == ["2"]
    assert outcome.binned == ["2"]


def test_ticking_nothing_bins_nothing():
    graph, gmail = started()
    outcome = resume_approval(graph, "2026-11-22", [])
    assert gmail.trashed == []
    assert outcome.status == "kept"


def test_a_second_answer_to_a_finished_thread_does_nothing():
    graph, gmail = started()
    resume_approval(graph, "2026-11-22", ["1"])
    outcome = resume_approval(graph, "2026-11-22", ["2", "3"])
    assert outcome.status == "already_done"
    assert gmail.trashed == ["1"]
    assert pending_items(graph, "2026-11-22") is None


def test_an_unknown_thread_is_not_found():
    graph, gmail = started()
    outcome = resume_approval(graph, "1999-01-01", ["1"])
    assert outcome.status == "not_found"
    assert gmail.trashed == []
    assert pending_items(graph, "1999-01-01") is None


def test_one_failed_move_does_not_stop_the_rest():
    graph, gmail = started(FakeGmail(fail={"2"}))
    outcome = resume_approval(graph, "2026-11-22", ["1", "2", "3"])
    assert gmail.trashed == ["1", "3"]
    assert outcome.binned == ["1", "3"]
    assert outcome.failed == ["2"]


def test_each_daily_run_is_its_own_thread():
    gmail = FakeGmail()
    graph = build_approval_graph(gmail, InMemorySaver())
    start_approval(graph, "day-1", CleanupList(items=[item("1")]))
    start_approval(graph, "day-2", CleanupList(items=[item("2")]))
    resume_approval(graph, "day-2", ["2"])
    assert gmail.trashed == ["2"]
    assert [i.email_id for i in pending_items(graph, "day-1")] == ["1"]


def test_the_saved_state_holds_only_the_clean_up_list():
    graph, _ = started()
    values = graph.get_state({"configurable": {"thread_id": "2026-11-22"}}).values
    assert set(values) == {"items"}
    assert set(values["items"][0].model_dump()) == {
        "email_id",
        "sender",
        "subject",
        "summary",
    }
