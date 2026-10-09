import pytest

from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.conversations.parts import TextPartInput
from a2a_workbench.core.errors import AgentCallError
from a2a_workbench.fixtures.runner import ZooServer


async def _working_task(wb, agent, text="slow 20"):
    conv = await wb.conversations.create(agent.id)
    events = [
        e
        async for e in wb.conversations.send(
            conv.id, [TextPartInput(text=text)], SendOptions(stream=False, return_immediately=True)
        )
    ]
    return next(e.task_id for e in events if e.task_id)


async def test_push_config_crud_round_trip(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)
    assert agent.card["capabilities"]["pushNotifications"] is True
    task_id = await _working_task(wb, agent)
    created = await wb.push.create(
        agent.id,
        task_id,
        url="https://hooks.example/a",
        token="tok-1",
        auth_scheme="Bearer",
        auth_credentials="cred-1",
        config_id="cfg-a",
    )
    assert created == {
        "id": "cfg-a",
        "taskId": task_id,
        "url": "https://hooks.example/a",
        "token": "tok-1",
        "authentication": {"scheme": "Bearer", "credentials": "cred-1"},
    }
    assert (await wb.push.get(agent.id, task_id, "cfg-a"))["url"] == "https://hooks.example/a"
    await wb.push.create(agent.id, task_id, url="https://hooks.example/b", config_id="cfg-b")
    listed = await wb.push.list(agent.id, task_id)
    assert {c["id"] for c in listed["configs"]} == {"cfg-a", "cfg-b"}
    await wb.push.delete(agent.id, task_id, "cfg-a")
    await wb.push.delete(agent.id, task_id, "cfg-a")  # A2A §3.1.10: idempotent
    assert [c["id"] for c in (await wb.push.list(agent.id, task_id))["configs"]] == ["cfg-b"]


async def test_unknown_task_is_task_not_found(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)
    with pytest.raises(AgentCallError) as info:
        await wb.push.create(agent.id, "no-such-task", url="https://hooks.example/a")
    assert info.value.classified["category"] == "protocol"
    assert "TASK_NOT_FOUND" in (info.value.classified.get("reason") or "").upper()


async def test_agent_without_push_returns_not_supported(wb):
    async with ZooServer(grpc=False, push=False) as zoo:
        agent = await wb.agents.add(zoo.base_url)
        assert not agent.card["capabilities"].get("pushNotifications")
        task_id = await _working_task(wb, agent, "slow 5")
        with pytest.raises(AgentCallError) as info:
            await wb.push.create(agent.id, task_id, url="https://hooks.example/a")
    assert "PUSH_NOTIFICATION_NOT_SUPPORTED" in (info.value.classified.get("reason") or "").upper()
