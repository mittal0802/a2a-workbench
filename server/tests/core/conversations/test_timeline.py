import pytest
from a2a.types import (
    Artifact,
    Message,
    Part,
    Role,
    StreamResponse,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)

from a2a_workbench.core.conversations.artifacts import ArtifactAssembler
from a2a_workbench.core.conversations.timeline import event_from_stream_response


def _conv(resp):
    return event_from_stream_response(
        resp, conversation_id="c", assembler=ArtifactAssembler(), exchange_id="e"
    )


def test_task_event():
    ev = _conv(
        StreamResponse(
            task=Task(
                id="t", context_id="x", status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED)
            )
        )
    )
    assert (ev.kind, ev.task_id, ev.context_id, ev.exchange_id) == ("task", "t", "x", "e")
    assert ev.data["state"] == "submitted" and ev.data["task"]["id"] == "t"


def test_message_event():
    ev = _conv(
        StreamResponse(
            message=Message(
                message_id="m", context_id="x", role=Role.ROLE_AGENT, parts=[Part(text="hi")]
            )
        )
    )
    assert ev.kind == "message" and ev.task_id is None and ev.context_id == "x"
    assert ev.data["message"]["parts"] == [{"text": "hi"}]


def test_status_event():
    ev = _conv(
        StreamResponse(
            status_update=TaskStatusUpdateEvent(
                task_id="t",
                context_id="x",
                status=TaskStatus(state=TaskState.TASK_STATE_INPUT_REQUIRED),
            )
        )
    )
    assert ev.kind == "status" and ev.data["state"] == "input_required"
    assert ev.data["metadata"] is None


def test_artifact_event_includes_assembled():
    asm = ArtifactAssembler()
    r1 = StreamResponse(
        artifact_update=TaskArtifactUpdateEvent(
            task_id="t", context_id="x", artifact=Artifact(artifact_id="a", parts=[Part(text="1")])
        )
    )
    r2 = StreamResponse(
        artifact_update=TaskArtifactUpdateEvent(
            task_id="t",
            context_id="x",
            append=True,
            last_chunk=True,
            artifact=Artifact(artifact_id="a", parts=[Part(text="2")]),
        )
    )
    event_from_stream_response(r1, conversation_id="c", assembler=asm, exchange_id=None)
    ev = event_from_stream_response(r2, conversation_id="c", assembler=asm, exchange_id=None)
    assert ev.data["append"] is True and ev.data["last_chunk"] is True
    assert ev.data["assembled"]["parts"] == [{"text": "1"}, {"text": "2"}]


def test_empty_stream_response_raises():
    with pytest.raises(ValueError):
        _conv(StreamResponse())
