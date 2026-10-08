"""Normalized conversation timeline events."""

from datetime import UTC, datetime
from typing import Any, Literal

from a2a.types import StreamResponse
from pydantic import BaseModel, Field

from a2a_workbench.core.a2a_json import state_name, to_json
from a2a_workbench.core.conversations.artifacts import ArtifactAssembler

EventKind = Literal[
    "user_message",
    "message",
    "task",
    "status",
    "artifact",
    "error",
    "connection_lost",
    "recovered",
]


class TimelineEvent(BaseModel):
    """One entry of a conversation timeline, in a binding-independent shape."""

    conversation_id: str
    seq: int = 0
    kind: EventKind
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    task_id: str | None = None
    context_id: str | None = None
    exchange_id: str | None = None
    data: dict[str, Any]


def event_from_stream_response(
    resp: StreamResponse,
    *,
    conversation_id: str,
    assembler: ArtifactAssembler,
    exchange_id: str | None,
) -> TimelineEvent:
    """Convert one SDK ``StreamResponse`` into a ``TimelineEvent``.

    Artifact updates are merged through ``assembler``; the event carries both the
    received chunk and the assembled artifact.

    Raises:
        ValueError: if ``resp`` carries no payload.
    """
    payload = resp.WhichOneof("payload")
    common: dict[str, Any] = {"conversation_id": conversation_id, "exchange_id": exchange_id}
    if payload == "task":
        task = resp.task
        for artifact in task.artifacts:
            assembler.seed(task.id, artifact)
        return TimelineEvent(
            kind="task",
            task_id=task.id,
            context_id=task.context_id or None,
            data={"task": to_json(task), "state": state_name(task.status.state)},
            **common,
        )
    if payload == "message":
        msg = resp.message
        return TimelineEvent(
            kind="message",
            task_id=msg.task_id or None,
            context_id=msg.context_id or None,
            data={"message": to_json(msg)},
            **common,
        )
    if payload == "status_update":
        su = resp.status_update
        return TimelineEvent(
            kind="status",
            task_id=su.task_id,
            context_id=su.context_id or None,
            data={
                "state": state_name(su.status.state),
                "status": to_json(su.status),
                "metadata": to_json(su.metadata) if su.metadata.fields else None,
            },
            **common,
        )
    if payload == "artifact_update":
        au = resp.artifact_update
        assembled = assembler.apply(au)
        return TimelineEvent(
            kind="artifact",
            task_id=au.task_id,
            context_id=au.context_id or None,
            data={
                "artifact": to_json(au.artifact),
                "append": au.append,
                "last_chunk": au.last_chunk,
                "assembled": to_json(assembled),
            },
            **common,
        )
    raise ValueError(f"StreamResponse has no payload: {payload!r}")
