import pytest

from a2a_workbench.core.assistant.executor import AgentCallExecutor
from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.conversations.parts import TextPartInput
from a2a_workbench.fixtures.runner import ZooServer


@pytest.fixture
async def agent(wb, zoo):
    return await wb.agents.add(zoo.base_url)


async def test_new_call_creates_assistant_conversation(wb, agent):
    result = await AgentCallExecutor(wb).call(
        agent.id, {"message": "echo hi"}, conversation_id=None, timeout_s=30
    )
    conv = await wb.conversations.get(result.conversation_id)
    assert conv.origin == "assistant"
    assert result.kind == "task" and result.state == "completed"
    assert result.artifacts[0]["parts"][0] == {"kind": "text", "text": "echo hi"}
    assert result.context_id and result.task_id and not result.warnings


async def test_continuation_uses_exact_ids(wb, agent):
    ex = AgentCallExecutor(wb)
    first = await ex.call(agent.id, {"message": "ask"}, conversation_id=None, timeout_s=30)
    assert (
        first.state == "input_required" and first.question == "Which option should I pick: A or B?"
    )
    second = await ex.call(
        agent.id,
        {"message": "B", "task_id": first.task_id, "context_id": first.context_id},
        conversation_id=first.conversation_id,
        timeout_s=30,
    )
    assert second.state == "completed" and second.artifacts[0]["parts"][0]["text"] == "You chose: B"
    sent = [
        e for e in await wb.conversations.events(first.conversation_id) if e.kind == "user_message"
    ][-1]
    assert sent.data["message"]["taskId"] == first.task_id
    assert sent.data["message"]["contextId"] == first.context_id


async def test_inherit_ids_false_does_not_attach_open_task(wb, agent):
    ex = AgentCallExecutor(wb)
    first = await ex.call(agent.id, {"message": "ask"}, conversation_id=None, timeout_s=30)
    again = await ex.call(
        agent.id, {"message": "echo fresh"}, conversation_id=first.conversation_id, timeout_s=30
    )
    assert again.task_id != first.task_id and again.state == "completed"
    sent = [
        e for e in await wb.conversations.events(first.conversation_id) if e.kind == "user_message"
    ][-1]
    assert "taskId" not in sent.data["message"] and "contextId" not in sent.data["message"]


async def test_chat_still_continues_the_open_task_by_default(wb, agent):
    conv = await wb.conversations.create(agent.id)
    [
        e
        async for e in wb.conversations.send(
            conv.id, [TextPartInput(text="ask")], SendOptions(stream=False)
        )
    ]
    done = [
        e
        async for e in wb.conversations.send(
            conv.id, [TextPartInput(text="A")], SendOptions(stream=False)
        )
    ]
    assert done[-1].data["state"] == "completed"


async def test_message_reply_has_context_and_no_task(wb, agent):
    result = await AgentCallExecutor(wb).call(
        agent.id, {"message": "message hello"}, conversation_id=None, timeout_s=30
    )
    assert result.kind == "message" and result.task_id is None
    assert result.messages == ["Direct reply: hello"] and result.context_id


async def test_output_only_in_messages_gets_section_3_7_warning(wb, agent):
    result = await AgentCallExecutor(wb).call(
        agent.id, {"message": "note milk"}, conversation_id=None, timeout_s=30
    )
    assert result.state == "completed" and not result.artifacts
    assert "Noted: milk" in result.messages
    assert any("§3.7" in w for w in result.warnings)


async def test_dropped_stream_is_resubscribed_once(wb, agent):
    from a2a_workbench.core.faults.profile import load_profile

    ex = AgentCallExecutor(wb)
    result = await ex.call(
        agent.id,
        {"message": "long"},
        conversation_id=None,
        timeout_s=30,
        faults=load_profile("flaky_stream"),
    )
    assert result.state == "completed" and result.error is None
    assert any("resubscribed" in w.lower() for w in result.notes)
    kinds = [e.kind for e in await wb.conversations.events(result.conversation_id)]
    assert "connection_lost" in kinds and "recovered" in kinds


async def test_timeout_returns_running_state(wb, agent):
    result = await AgentCallExecutor(wb).call(
        agent.id, {"message": "stall 5"}, conversation_id=None, timeout_s=0.8
    )
    assert result.state in ("working", "submitted")
    assert any("get_task" in w for w in result.notes)


async def test_auth_error_result(wb):
    async with ZooServer(auth="bearer", grpc=False) as zoo:
        agent = await wb.agents.add(zoo.base_url)
        result = await AgentCallExecutor(wb).call(
            agent.id, {"message": "echo"}, conversation_id=None, timeout_s=30
        )
    assert result.kind == "error" and result.error["category"] == "auth"


async def test_data_and_file_parts_are_sent(wb, agent):
    result = await AgentCallExecutor(wb).call(
        agent.id,
        {"message": "inspect", "data": {"n": 1}, "file_urls": ["https://example.com/a.png"]},
        conversation_id=None,
        timeout_s=30,
    )
    received = result.artifacts[0]["parts"][0]["data"]
    assert received["message"]["parts"][1]["data"] == {"n": 1}


async def test_get_task_and_for_llm(wb, agent):
    ex = AgentCallExecutor(wb)
    first = await ex.call(agent.id, {"message": "ask"}, conversation_id=None, timeout_s=30)
    got = await ex.get_task(agent.id, first.task_id)
    assert got.state == "input_required" and got.task_id == first.task_id
    import json

    text = json.loads(first.for_llm(shown_to_user=True))
    assert text["state"] == "input_required" and text["shown_to_user"] is True
