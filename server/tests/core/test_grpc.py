import pytest
from a2a.types import AgentCard, AgentInterface, Message, Part, Role, SendMessageRequest, TaskState

from a2a_workbench.core.connection.cards import fetch_card
from a2a_workbench.core.connection.client import open_client
from a2a_workbench.core.connection.grpc import parse_grpc_target
from a2a_workbench.core.connection.recorder import recording_scope
from a2a_workbench.core.conversations.errors import classify_error
from a2a_workbench.core.faults.profile import FaultProfile, FaultRule


class Sink(list):
    async def __call__(self, ex):
        if ex.complete:
            self.append(ex)


def test_parse_grpc_target():
    assert parse_grpc_target("localhost:50051") == ("localhost:50051", False)
    assert parse_grpc_target("grpc://h:1") == ("h:1", False)
    assert parse_grpc_target("http://h:1/a2a") == ("h:1", False)
    assert parse_grpc_target("grpcs://h:443") == ("h:443", True)
    assert parse_grpc_target("https://h") == ("h:443", True)
    assert parse_grpc_target("http://h") == ("h:80", False)


def _req(text):
    return SendMessageRequest(
        message=Message(message_id="m", role=Role.ROLE_USER, parts=[Part(text=text)])
    )


async def _grpc(zoo, sink):
    card = (await fetch_card(zoo.base_url, sink)).card
    iface = next(i for i in card.supported_interfaces if i.protocol_binding == "GRPC")
    return card, iface


async def test_grpc_streaming_round_trip_is_recorded(zoo):
    sink = Sink()
    card, iface = await _grpc(zoo, sink)
    with recording_scope("send_message"):
        async with await open_client(card, iface, sink, streaming=True) as client:
            events = [e async for e in client.send_message(_req("stream"))]
    assert events[-1].status_update.status.state == TaskState.TASK_STATE_COMPLETED
    ex = [e for e in sink if e.http_method == "GRPC"][-1]
    assert ex.url.endswith("/SendStreamingMessage") and ex.operation == "send_message"
    assert len(ex.frames) == len(events) and ex.status == 0
    assert '"stream"' in ex.request_body


async def test_grpc_unary_round_trip(zoo):
    sink = Sink()
    card, iface = await _grpc(zoo, sink)
    async with await open_client(card, iface, sink, streaming=False) as client:
        events = [e async for e in client.send_message(_req("echo hi"))]
    assert events[-1].task.status.state == TaskState.TASK_STATE_COMPLETED
    ex = [e for e in sink if e.http_method == "GRPC"][-1]
    assert ex.url.endswith("/SendMessage") and '"echo hi"' in ex.response_body


async def test_grpc_unreachable_is_transport_error():
    card = AgentCard(
        name="x",
        supported_interfaces=[
            AgentInterface(url="127.0.0.1:1", protocol_binding="GRPC", protocol_version="1.0")
        ],
    )
    async with await open_client(card, card.supported_interfaces[0], Sink(), streaming=False) as c:
        with pytest.raises(Exception) as info:
            [e async for e in c.send_message(_req("echo"))]
    assert classify_error(info.value)["category"] == "transport"


async def test_grpc_drop_stream_fault(zoo):
    sink = Sink()
    card, iface = await _grpc(zoo, sink)
    faults = FaultProfile(rules=[FaultRule(kind="drop_stream", params={"after_events": 2})])
    got = []
    async with await open_client(card, iface, sink, streaming=True, faults=faults) as client:
        with pytest.raises(Exception) as info:
            async for e in client.send_message(_req("stream")):
                got.append(e)
    assert len(got) == 2
    assert classify_error(info.value)["category"] == "transport"
    assert [e for e in sink if e.http_method == "GRPC"][-1].fault == "drop_stream"


async def test_grpc_status_fault_maps_to_auth(zoo):
    sink = Sink()
    card, iface = await _grpc(zoo, sink)
    faults = FaultProfile(rules=[FaultRule(kind="http_status", params={"code": 401})])
    async with await open_client(card, iface, sink, streaming=False, faults=faults) as client:
        with pytest.raises(Exception) as info:
            [e async for e in client.send_message(_req("echo"))]
    assert classify_error(info.value)["category"] == "auth"


async def test_http_faults_through_open_client(zoo):
    sink = Sink()
    card = (await fetch_card(zoo.base_url, sink)).card
    iface = next(i for i in card.supported_interfaces if i.protocol_binding == "JSONRPC")
    faults = FaultProfile(rules=[FaultRule(kind="refuse")])
    with recording_scope("send_message"):
        async with await open_client(card, iface, sink, streaming=False, faults=faults) as c:
            with pytest.raises(Exception) as info:
                [e async for e in c.send_message(_req("echo"))]
    assert classify_error(info.value)["category"] == "transport"
    assert sink[-1].fault == "refuse"


async def test_grpc_drop_after_ms_fires_while_the_stream_is_silent(zoo):
    import time

    sink = Sink()
    card, iface = await _grpc(zoo, sink)
    faults = FaultProfile(rules=[FaultRule(kind="drop_stream", params={"after_ms": 300})])
    start = time.monotonic()
    async with await open_client(card, iface, sink, streaming=True, faults=faults) as client:
        with pytest.raises(Exception) as info:
            [e async for e in client.send_message(_req("stall 4"))]
    assert time.monotonic() - start < 2
    assert classify_error(info.value)["category"] == "transport"
