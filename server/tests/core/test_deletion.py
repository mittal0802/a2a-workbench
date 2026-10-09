import pytest

from a2a_workbench.core.assistant.service import AssistantService, SessionIn, SessionNotFoundError
from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.conversations.parts import TextPartInput
from a2a_workbench.core.conversations.service import ConversationNotFoundError
from a2a_workbench.fixtures.llm import ScriptedAdapter


async def test_delete_conversation_removes_events_and_exchanges(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)
    conv = await wb.conversations.create(agent.id)
    [
        e
        async for e in wb.conversations.send(
            conv.id, [TextPartInput(text="echo")], SendOptions(stream=False)
        )
    ]
    assert await wb.exchanges.list(conversation_id=conv.id)
    await wb.conversations.delete(conv.id)
    with pytest.raises(ConversationNotFoundError):
        await wb.conversations.get(conv.id)
    assert await wb.exchanges.list(conversation_id=conv.id) == []
    with pytest.raises(ConversationNotFoundError):
        await wb.conversations.delete(conv.id)


async def test_delete_assistant_chat_removes_steps_and_llm_calls(wb, zoo):
    await wb.provider_keys.put("openai", "k-123456")
    svc = AssistantService(wb, adapter_factory=lambda *a, **k: ScriptedAdapter())
    agent = await wb.agents.add(zoo.base_url)
    s = await svc.create(SessionIn(provider="openai", model="m", agent_ids=[agent.id]))
    [st async for st in svc.send(s.id, "echo hi")]
    await svc.delete(s.id)
    with pytest.raises(SessionNotFoundError):
        await svc.get(s.id)
    assert await svc.list() == []
    await svc.close()


async def test_chat_keeps_working_after_one_of_its_agents_is_removed(wb, zoo):
    from a2a_workbench.fixtures.runner import ZooServer

    await wb.provider_keys.put("openai", "k-123456")
    svc = AssistantService(wb, adapter_factory=lambda *a, **k: ScriptedAdapter())
    async with ZooServer(grpc=False, card_path="/other/card.json") as other:
        a1 = await wb.agents.add(zoo.base_url)
        a2 = await wb.agents.add(f"{other.base_url}/other/card.json")
        s = await svc.create(SessionIn(provider="openai", model="m", agent_ids=[a2.id, a1.id]))
        await wb.agents.remove(a2.id)
        steps = [st async for st in svc.send(s.id, "echo still here")]
    assert steps[-1].kind == "done" and steps[-1].data["text"] == "Done: echo still here"
    await svc.close()
