import pytest

from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.conversations.parts import TextPartInput


async def _chat(wb, agent_id, text, **opts):
    conv = await wb.conversations.create(agent_id)
    return [
        e
        async for e in wb.conversations.send(
            conv.id, [TextPartInput(text=text)], SendOptions(**opts)
        )
    ]


async def test_legacy_card_lists_v03_interfaces(wb, legacy_zoo):
    agent = await wb.agents.add(legacy_zoo.base_url)
    assert {i.protocol_version for i in agent.interfaces} == {"0.3"}
    assert {i.binding for i in agent.interfaces} == {"JSONRPC", "HTTP+JSON", "GRPC"}


async def test_legacy_v03_agent_round_trip(wb, legacy_zoo):
    agent = await wb.agents.add(legacy_zoo.base_url)
    events = await _chat(wb, agent.id, "stream")
    assert events[-1].data["state"] == "completed"
    ex = await wb.exchanges.get(events[-1].exchange_id)
    assert '"message/stream"' in ex["request_body"]


@pytest.mark.parametrize("binding", ["HTTP+JSON", "GRPC"])
async def test_legacy_other_bindings(wb, legacy_zoo, binding):
    agent = await wb.agents.add(legacy_zoo.base_url)
    iface = next(i for i in agent.interfaces if i.binding == binding)
    await wb.agents.set_interface(agent.id, iface.url)
    events = await _chat(wb, agent.id, "echo v03", stream=False)
    assert events[-1].data["state"] == "completed"
