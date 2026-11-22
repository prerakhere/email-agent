"""The approval graph: START -> approval -> bin -> END, paused in the middle for the owner.

The daily run starts a thread right after sending the digest (whose link names the thread). The
`approval` node calls `interrupt()`: the run stops there and the checkpointer saves its state, which
holds only the clean-up list (ids, senders, subjects, summaries), never email bodies. When the owner
submits the approval page, the same thread is resumed with `Command(resume=<ticked ids>)`; the node
keeps only ids that were on the original list, and `bin` moves those to Gmail's Bin (30 days).

Like Step Functions' "wait for a task token": the workflow parks until someone calls back.
"""

import logging
from dataclasses import dataclass, field
from typing import Literal, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from agent.cleanup import CleanupItem, CleanupList

log = logging.getLogger(__name__)


class ApprovalState(TypedDict, total=False):
    items: list[
        CleanupItem
    ]  # what was offered: the only mail this thread may ever touch
    approved_ids: list[str]
    binned: list[str]
    failed: list[str]


@dataclass
class ApprovalOutcome:
    status: Literal["binned", "kept", "already_done", "not_found"]
    binned: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def build_approval_graph(gmail, checkpointer: BaseCheckpointSaver):
    def approval_node(state: ApprovalState) -> dict:
        # The run pauses here. On resume, interrupt() returns what the owner sent: the ticked ids.
        chosen = interrupt({"count": len(state["items"])})
        ticked = (
            {i for i in chosen if isinstance(i, str)}
            if isinstance(chosen, list)
            else set()
        )
        # Never trust the page: keep only mail that was on the list this thread offered.
        return {
            "approved_ids": [i.email_id for i in state["items"] if i.email_id in ticked]
        }

    def route_after_approval(state: ApprovalState) -> str:
        return "bin" if state["approved_ids"] else END

    def bin_node(state: ApprovalState) -> dict:
        binned, failed = [], []
        for email_id in state["approved_ids"]:
            try:
                gmail.trash(email_id)
                binned.append(email_id)
            except Exception as error:  # noqa: BLE001 - one failure must not stop the rest
                log.warning(
                    "could not move a message to the bin: %s", type(error).__name__
                )
                failed.append(email_id)
        return {"binned": binned, "failed": failed}

    graph = StateGraph(ApprovalState)
    graph.add_node("approval", approval_node)
    graph.add_node("bin", bin_node)
    graph.add_edge(START, "approval")
    graph.add_conditional_edges("approval", route_after_approval, ["bin", END])
    graph.add_edge("bin", END)
    # The checkpointer is what lets a run stop at interrupt() and continue in another process.
    return graph.compile(checkpointer=checkpointer)


def start_approval(graph, thread_id: str, cleanup: CleanupList) -> None:
    """Run a new thread up to the pause. Nothing is moved."""
    graph.invoke({"items": cleanup.items}, _config(thread_id))


def _waiting(graph, thread_id: str):
    """The thread's saved state, and whether it is paused at the approval step."""
    snapshot = graph.get_state(_config(thread_id))
    return snapshot, bool(snapshot.values) and "approval" in snapshot.next


def pending_items(graph, thread_id: str) -> list[CleanupItem] | None:
    """What the approval page lists; None when the thread is unknown or already answered."""
    snapshot, waiting = _waiting(graph, thread_id)
    return snapshot.values["items"] if waiting else None


def resume_approval(graph, thread_id: str, chosen_ids: list[str]) -> ApprovalOutcome:
    """Answer a paused thread with the ticked ids. A thread can be answered once."""
    snapshot, waiting = _waiting(graph, thread_id)
    if not snapshot.values:
        return ApprovalOutcome("not_found")
    if not waiting:
        return ApprovalOutcome("already_done")
    final = graph.invoke(Command(resume=list(chosen_ids)), _config(thread_id))
    binned, failed = final.get("binned", []), final.get("failed", [])
    return ApprovalOutcome("binned" if binned or failed else "kept", binned, failed)
