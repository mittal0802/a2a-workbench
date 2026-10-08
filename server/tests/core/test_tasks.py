import pytest

from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.conversations.parts import TextPartInput
from a2a_workbench.core.errors import AgentCallError
from a2a_workbench.core.faults.profile import FaultProfile, FaultRule
from a2a_workbench.core.tasks.service import ListTasksFilter


async def _send(wb, conv_id, text, **opts):
    return [
        e
        async for e in wb.conversations.send(
            conv_id, [TextPartInput(text=text)], SendOptions(**opts)
        )
    ]


async def _conv_with_tasks(wb, agent, n):
    conv = await wb.conversations.create(agent.id)
    for i in range(n):
        await _send(wb, conv.id, f"echo {i}", stream=False)
    return await wb.conversations.get(conv.id)


@pytest.fixture
async def agent(wb, zoo):
    return await wb.agents.add(zoo.base_url)


async def test_get_task_with_history_length(wb, agent):
    conv = await _conv_with_tasks(wb, agent, 1)
    task = await wb.tasks.get(agent.id, conv.task_id, history_length=1)
    assert task["id"] == conv.task_id and task["state"] == "completed"
    assert len(task.get("history", [])) <= 1


async def test_list_tasks_filters_by_status_and_context(wb, agent):
    conv = await _conv_with_tasks(wb, agent, 2)
    out = await wb.tasks.list(
        agent.id, ListTasksFilter(context_id=conv.context_id, status="completed")
    )
    assert len(out["tasks"]) == 2
    assert all(
        t["contextId"] == conv.context_id and t["state"] == "completed" for t in out["tasks"]
    )


async def test_list_tasks_pagination_covers_all(wb, agent):
    conv = await _conv_with_tasks(wb, agent, 5)
    seen, token = [], None
    while True:
        page = await wb.tasks.list(
            agent.id, ListTasksFilter(context_id=conv.context_id, page_size=2, page_token=token)
        )
        seen += [t["id"] for t in page["tasks"]]
        token = page.get("next_page_token")
        if not token:
            break
    assert len(seen) == 5 and len(set(seen)) == 5


async def test_cancel_unknown_task_is_protocol_error(wb, agent):
    with pytest.raises(AgentCallError) as info:
        await wb.tasks.cancel(agent.id, "nope")
    assert info.value.classified["category"] == "protocol"
    assert info.value.classified["reason"] == "TASK_NOT_FOUND"


async def test_cancel_running_task(wb, agent):
    conv = await wb.conversations.create(agent.id)
    await _send(wb, conv.id, "slow 20", stream=False, return_immediately=True)
    task_id = (await wb.conversations.get(conv.id)).task_id
    assert (await wb.tasks.cancel(agent.id, task_id))["state"] == "canceled"


async def test_subscribe_running_task_yields_snapshot_first(wb, agent):
    conv = await wb.conversations.create(agent.id)
    await _send(wb, conv.id, "long", stream=False, return_immediately=True)
    task_id = (await wb.conversations.get(conv.id)).task_id
    events = [e async for e in wb.tasks.subscribe(agent.id, task_id)]
    assert events[0]["kind"] == "task"
    assert events[-1]["kind"] == "status_update" and events[-1]["state"] == "completed"


async def test_task_operations_record_their_operation(wb, agent):
    conv = await _conv_with_tasks(wb, agent, 1)
    await wb.tasks.get(agent.id, conv.task_id)
    ops = {e["operation"] for e in await wb.exchanges.list(agent_id=agent.id)}
    assert "get_task" in ops


async def test_task_operations_accept_faults(wb, agent):
    conv = await _conv_with_tasks(wb, agent, 1)
    with pytest.raises(AgentCallError) as info:
        await wb.tasks.get(
            agent.id, conv.task_id, faults=FaultProfile(rules=[FaultRule(kind="refuse")])
        )
    assert info.value.classified["category"] == "transport"


@pytest.mark.parametrize("binding", ["HTTP+JSON", "GRPC"])
async def test_list_tasks_over_other_bindings(wb, agent, binding):
    iface = next(i for i in agent.interfaces if i.binding == binding)
    await wb.agents.set_interface(agent.id, iface.url)
    conv = await _conv_with_tasks(wb, agent, 1)
    out = await wb.tasks.list(agent.id, ListTasksFilter(context_id=conv.context_id))
    assert [t["id"] for t in out["tasks"]] == [conv.task_id]
