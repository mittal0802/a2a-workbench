import pytest
from a2a.types import (
    AgentCard,
    AgentInterface,
    Message,
    Part,
    Role,
    SendMessageRequest,
    TaskState,
)

from a2a_workbench.core.connection.cards import fetch_card
from a2a_workbench.core.connection.client import (
    InterfaceNotFoundError,
    UnsupportedBindingError,
    card_for_interface,
    open_client,
    select_interface,
)


def _card(*ifaces):
    return AgentCard(
        name="x",
        supported_interfaces=[
            AgentInterface(url=u, protocol_binding=b, protocol_version=v) for u, b, v in ifaces
        ],
    )


async def _sink(_):
    return None


def test_select_default_prefers_jsonrpc_v1():
    card = _card(
        ("g", "GRPC", "1.0"),
        ("r", "HTTP+JSON", "1.0"),
        ("j3", "JSONRPC", "0.3"),
        ("j1", "JSONRPC", "1.0"),
    )
    assert select_interface(card, None).url == "j1"


def test_select_by_url():
    card = _card(("j", "JSONRPC", "1.0"), ("r", "HTTP+JSON", "1.0"))
    assert select_interface(card, "r").protocol_binding == "HTTP+JSON"


def test_select_unknown_url_raises():
    with pytest.raises(InterfaceNotFoundError):
        select_interface(_card(("j", "JSONRPC", "1.0")), "nope")


def test_select_on_card_without_interfaces_raises():
    with pytest.raises(InterfaceNotFoundError):
        select_interface(AgentCard(name="x"), None)


def test_card_for_interface_keeps_only_chosen():
    card = _card(("j", "JSONRPC", "1.0"), ("r", "HTTP+JSON", "1.0"))
    narrowed = card_for_interface(card, card.supported_interfaces[1])
    assert [i.url for i in narrowed.supported_interfaces] == ["r"]
    assert len(card.supported_interfaces) == 2


async def test_unknown_binding_is_unsupported():
    card = _card(("x", "WEBSOCKET", "1.0"))
    with pytest.raises(UnsupportedBindingError):
        await open_client(card, card.supported_interfaces[0], _sink, streaming=True)


@pytest.mark.parametrize("binding", ["JSONRPC", "HTTP+JSON", "GRPC"])
@pytest.mark.parametrize("streaming", [True, False])
async def test_send_over_each_binding(zoo, binding, streaming):
    result = await fetch_card(zoo.base_url, _sink)
    iface = next(i for i in result.card.supported_interfaces if i.protocol_binding == binding)
    req = SendMessageRequest(
        message=Message(message_id="m", role=Role.ROLE_USER, parts=[Part(text="echo hi")])
    )
    async with await open_client(result.card, iface, _sink, streaming=streaming) as client:
        events = [e async for e in client.send_message(req)]
    last = events[-1]
    state = (
        last.task.status.state
        if last.WhichOneof("payload") == "task"
        else last.status_update.status.state
    )
    assert state == TaskState.TASK_STATE_COMPLETED
