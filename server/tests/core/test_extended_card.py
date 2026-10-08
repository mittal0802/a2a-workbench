import pytest

from a2a_workbench.core.errors import AgentCallError


async def test_extended_card_fetch_and_diff(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)
    out = await wb.agents.get_extended_card(agent.id)
    assert out.card["name"] == "Zoo agent"
    assert any(d["path"] == "skills[visa]" and d["change"] == "added" for d in out.diff)
    assert out.exchange_ids
    assert (await wb.agents.row(agent.id)).extended_card["name"] == "Zoo agent"


@pytest.mark.parametrize("binding", ["HTTP+JSON", "GRPC"])
async def test_extended_card_over_other_bindings(wb, zoo, binding):
    agent = await wb.agents.add(zoo.base_url)
    iface = next(i for i in agent.interfaces if i.binding == binding)
    await wb.agents.set_interface(agent.id, iface.url)
    assert any(
        d["path"] == "skills[visa]" for d in (await wb.agents.get_extended_card(agent.id)).diff
    )


async def test_extended_card_not_declared_is_protocol_error(wb, legacy_zoo):
    agent = await wb.agents.add(legacy_zoo.base_url)
    with pytest.raises(AgentCallError) as info:
        await wb.agents.get_extended_card(agent.id)
    assert info.value.classified["reason"] == "NOT_DECLARED"
