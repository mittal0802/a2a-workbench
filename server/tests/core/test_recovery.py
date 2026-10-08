import pytest

from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.conversations.parts import TextPartInput
from a2a_workbench.core.faults.profile import FaultProfile, FaultRule

DROP = FaultProfile(rules=[FaultRule(kind="drop_stream", params={"after_events": 3})])


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


async def test_drop_produces_connection_lost(wb, conv):
    events = await _send(wb, conv.id, "long", faults=DROP)
    last = events[-1]
    assert last.kind == "connection_lost"
    assert last.data["task_id"] == last.task_id and last.data["last_state"] == "working"
    assert last.data["category"] == "transport"


async def test_transport_error_before_any_task_is_plain_error(wb, conv):
    events = await _send(wb, conv.id, "echo", faults=FaultProfile(rules=[FaultRule(kind="refuse")]))
    assert events[-1].kind == "error"


@pytest.mark.parametrize("binding", ["JSONRPC", "HTTP+JSON", "GRPC"])
async def test_resubscribe_after_dropped_stream_recovers_without_duplicates(wb, zoo, binding):
    agent = (
        await wb.agents.add(zoo.base_url)
        if not await wb.agents.list()
        else (await wb.agents.list())[0]
    )
    iface = next(i for i in agent.interfaces if i.binding == binding)
    await wb.agents.set_interface(agent.id, iface.url)
    conv = await wb.conversations.create(agent.id)
    await _send(wb, conv.id, "long", faults=DROP)
    after = [e async for e in wb.conversations.resubscribe(conv.id)]
    recovered = after[-1]
    assert recovered.kind == "recovered"
    assert recovered.data["method"] == "subscribe"
    assert recovered.data["snapshot_first"] is True
    assert recovered.data["state_after"] == "completed"
    assert recovered.data["duplicate_events"] == 0
    seqs = [e.seq for e in await wb.conversations.events(conv.id)]
    assert seqs == sorted(set(seqs))
    assert (await wb.conversations.get(conv.id)).task_state == "completed"


async def test_check_status_after_drop(wb, conv):
    await _send(wb, conv.id, "long", faults=DROP)
    after = [e async for e in wb.conversations.check_status(conv.id)]
    assert after[0].kind == "task"
    assert after[-1].kind == "recovered" and after[-1].data["method"] == "get_task"


async def test_resubscribe_without_task_is_error(wb, conv):
    after = [e async for e in wb.conversations.resubscribe(conv.id)]
    assert after[-1].kind == "error"


async def test_resubscribe_on_finished_task_reports_protocol_error(wb, conv):
    await _send(wb, conv.id, "echo done")
    after = [e async for e in wb.conversations.resubscribe(conv.id, force=True)]
    assert after[-1].kind == "error" and after[-1].data["category"] == "protocol"


@pytest.mark.parametrize(
    "rule",
    [
        {"kind": "truncate", "params": {"bytes": 1500}},
        {"kind": "truncate", "params": {"bytes": 10}},
        {"kind": "garble"},
    ],
)
async def test_byte_faults_on_streams_are_never_silent(wb, conv, rule):
    events = await _send(wb, conv.id, "long", faults=FaultProfile(rules=[rule]))
    assert events[-1].kind in {"error", "connection_lost"}


async def test_stream_that_ends_early_is_connection_lost(wb, conv):
    events = await _send(
        wb,
        conv.id,
        "long",
        faults=FaultProfile(rules=[{"kind": "truncate", "params": {"bytes": 1500}}]),
    )
    assert events[-1].kind == "connection_lost"


async def test_non_streaming_return_immediately_is_not_connection_lost(wb, conv):
    events = await _send(wb, conv.id, "slow 2", stream=False, return_immediately=True)
    assert events[-1].kind == "task"
