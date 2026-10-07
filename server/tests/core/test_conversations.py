import pytest
from sqlalchemy import update

from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.conversations.parts import DataPartInput, FilePartInput, TextPartInput
from a2a_workbench.core.store.models import Agent


async def _send(wb, conv_id, text, **opts):
    return [
        e
        async for e in wb.conversations.send(
            conv_id, [TextPartInput(text=text)], SendOptions(**opts)
        )
    ]


@pytest.fixture
async def conv(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)
    return await wb.conversations.create(agent.id)


async def test_streaming_echo_produces_ordered_events(wb, conv):
    events = await _send(wb, conv.id, "stream")
    kinds = [e.kind for e in events]
    assert kinds[0] == "user_message" and kinds[1] == "task"
    assert kinds.count("artifact") == 4
    assert events[-1].kind == "status" and events[-1].data["state"] == "completed"
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    assert events[-2].data["assembled"]["parts"][-1] == {"text": "pieces."}
    assert all(e.exchange_id for e in events[1:])
    stored = await wb.conversations.events(conv.id)
    assert [e.seq for e in stored] == [e.seq for e in events]
    exchanges = await wb.exchanges.list(conversation_id=conv.id)
    assert exchanges[-1]["operation"] == "send_message"
    assert exchanges[-1]["frame_count"] == len(events) - 1
    assert (await wb.conversations.get(conv.id)).title == "stream"


async def test_events_after_seq(wb, conv):
    events = await _send(wb, conv.id, "echo x")
    later = await wb.conversations.events(conv.id, after_seq=1)
    assert [e.seq for e in later] == [e.seq for e in events[1:]]


async def test_non_streaming_send(wb, conv):
    events = await _send(wb, conv.id, "echo hi", stream=False)
    assert [e.kind for e in events] == ["user_message", "task"]
    assert events[-1].data["state"] == "completed"


async def test_direct_message_reply(wb, conv):
    events = await _send(wb, conv.id, "message yo")
    assert events[-1].kind == "message"
    assert events[-1].data["message"]["parts"][0]["text"] == "Direct reply: yo"


async def test_reply_to_input_required_continues_task(wb, conv):
    first = await _send(wb, conv.id, "ask")
    assert first[-1].data["state"] == "input_required"
    task_id = first[-1].task_id
    assert (await wb.conversations.get(conv.id)).task_state == "input_required"
    second = await _send(wb, conv.id, "B")
    assert second[0].data["message"]["taskId"] == task_id
    assert second[-1].data["state"] == "completed" and second[-1].task_id == task_id


async def test_message_after_completion_starts_new_task_same_context(wb, conv):
    first = await _send(wb, conv.id, "echo one")
    second = await _send(wb, conv.id, "echo two")
    assert second[0].data["message"].get("taskId") is None
    assert second[0].data["message"]["contextId"] == first[1].context_id
    assert second[1].task_id != first[1].task_id


async def test_options_reach_the_agent(wb, conv):
    events = await _send(
        wb,
        conv.id,
        "inspect",
        accepted_output_modes=["application/json"],
        history_length=2,
        extensions=["https://example.com/ext/x"],
        message_metadata={"k": "v"},
    )
    report = next(e for e in events if e.kind == "artifact").data["assembled"]["parts"][0]["data"]
    assert report["configuration"]["acceptedOutputModes"] == ["application/json"]
    assert report["configuration"]["historyLength"] == 2
    assert report["requestedExtensions"] == ["https://example.com/ext/x"]
    assert report["message"]["metadata"] == {"k": "v"}


async def test_file_and_data_parts_are_sent(wb, conv):
    blob = await wb.blobs.put(b"hello", "text/plain", "h.txt")
    parts = [
        TextPartInput(text="inspect"),
        FilePartInput(blob_id=blob.id),
        DataPartInput(data={"n": 1}),
    ]
    events = [e async for e in wb.conversations.send(conv.id, parts, SendOptions())]
    sent = events[0].data["message"]["parts"]
    assert sent[1]["filename"] == "h.txt" and sent[1]["mediaType"] == "text/plain"
    assert sent[2]["data"] == {"n": 1}


async def test_missing_blob_is_reported_as_error_event(wb, conv):
    events = [
        e
        async for e in wb.conversations.send(
            conv.id, [FilePartInput(blob_id="nope")], SendOptions()
        )
    ]
    assert events[-1].kind == "error" and events[-1].data["category"] == "workbench"


async def test_cancel_running_task(wb, conv):
    await _send(wb, conv.id, "slow 30", return_immediately=True, stream=False)
    assert (await wb.conversations.get(conv.id)).task_state in {"submitted", "working"}
    cancel_events = [e async for e in wb.conversations.cancel(conv.id)]
    assert cancel_events[-1].data["state"] == "canceled"


async def test_cancel_without_running_task_is_error(wb, conv):
    events = [e async for e in wb.conversations.cancel(conv.id)]
    assert events[-1].kind == "error"


async def test_unreachable_agent_emits_transport_error(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)
    conv = await wb.conversations.create(agent.id)
    card = dict(agent.card)
    card["supportedInterfaces"] = [
        {"url": "http://127.0.0.1:1/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}
    ]
    async with wb.db.sessions() as s:
        await s.execute(
            update(Agent)
            .where(Agent.id == agent.id)
            .values(card=card, selected_interface_url="http://127.0.0.1:1/a2a")
        )
        await s.commit()
    events = await _send(wb, conv.id, "echo")
    assert events[-1].kind == "error" and events[-1].data["category"] == "transport"
    assert events[-1].exchange_id is not None
