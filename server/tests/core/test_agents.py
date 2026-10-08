import pytest

from a2a_workbench.core.connection.cards import CardFetchError
from a2a_workbench.core.connection.client import InterfaceNotFoundError
from a2a_workbench.core.registry.service import AgentExistsError, AgentNotFoundError


async def test_add_list_get_resolve_remove(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)
    assert agent.name == "Zoo agent" and agent.signature_status == "verified"
    assert agent.selected_interface_url == f"{zoo.base_url}/a2a"
    assert {i.binding for i in agent.interfaces} == {"JSONRPC", "HTTP+JSON", "GRPC"}
    assert all(i.supported for i in agent.interfaces)
    assert [a.id for a in await wb.agents.list()] == [agent.id]
    assert (await wb.agents.resolve("Zoo agent")).id == agent.id
    assert (await wb.agents.resolve(zoo.base_url)).id == agent.id
    assert (await wb.agents.resolve(agent.id)).id == agent.id
    await wb.agents.remove(agent.id)
    with pytest.raises(AgentNotFoundError):
        await wb.agents.get(agent.id)


async def test_add_twice_raises(wb, zoo):
    await wb.agents.add(zoo.base_url)
    with pytest.raises(AgentExistsError):
        await wb.agents.add(zoo.base_url + "/")


async def test_add_unreachable(wb):
    with pytest.raises(CardFetchError):
        await wb.agents.add("http://127.0.0.1:1")
    assert await wb.agents.list() == []


async def test_set_interface(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)
    updated = await wb.agents.set_interface(agent.id, f"{zoo.base_url}/v1")
    assert updated.selected_interface_url == f"{zoo.base_url}/v1"
    with pytest.raises(InterfaceNotFoundError):
        await wb.agents.set_interface(agent.id, "http://elsewhere")


async def test_refresh_keeps_selected_interface(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)
    await wb.agents.set_interface(agent.id, f"{zoo.base_url}/v1")
    refreshed = await wb.agents.refresh_card(agent.id)
    assert refreshed.selected_interface_url == f"{zoo.base_url}/v1"


async def test_remove_deletes_conversations(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)
    conv = await wb.conversations.create(agent.id)
    await wb.agents.remove(agent.id)
    from a2a_workbench.core.conversations.service import ConversationNotFoundError

    with pytest.raises(ConversationNotFoundError):
        await wb.conversations.get(conv.id)


async def test_preview_does_not_persist(wb, zoo):
    preview = await wb.agents.preview(zoo.base_url)
    assert preview.card["name"] == "Zoo agent"
    assert preview.default_interface_url == f"{zoo.base_url}/a2a"
    assert await wb.agents.list() == []
