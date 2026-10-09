import json

from a2a_workbench.core.assistant.llm import ChatMessage, ToolCall, ToolSpec, adapter_for
from a2a_workbench.fixtures.llm import FakeOpenAIServer, ScriptedAdapter, scripted_reply

TOOLS = [ToolSpec(name="call_zoo", description="d", input_schema={"type": "object"})]


def _result(state, **extra):
    return ChatMessage(
        role="tool",
        tool_call_id="c1",
        tool_name="call_zoo",
        text=json.dumps({"state": state, **extra}),
    )


def test_policy_calls_first_tool_with_the_user_text():
    reply = scripted_reply([ChatMessage(role="user", text="ask")], TOOLS)
    assert reply.tool_calls[0].name == "call_zoo" and reply.tool_calls[0].arguments == {
        "message": "ask"
    }


def test_policy_answers_a_question_on_the_same_task():
    history = [
        ChatMessage(role="user", text="ask"),
        ChatMessage(
            role="assistant",
            tool_calls=[ToolCall(id="c1", name="call_zoo", arguments={"message": "ask"})],
        ),
        _result("input_required", task_id="t1", context_id="x1", question="A or B?"),
    ]
    call = scripted_reply(history, TOOLS).tool_calls[0]
    assert call.arguments == {"message": "B", "task_id": "t1", "context_id": "x1"}


def test_policy_asks_the_user_when_told_to():
    history = [
        ChatMessage(role="user", text="ask me"),
        _result("input_required", question="A or B?"),
    ]
    reply = scripted_reply(history, TOOLS)
    assert reply.text == "Question from the agent: A or B?" and not reply.tool_calls


def test_policy_finishes_with_the_artifact_text():
    history = [
        ChatMessage(role="user", text="echo hi"),
        _result(
            "completed", artifacts=[{"name": "echo", "parts": [{"kind": "text", "text": "hi"}]}]
        ),
    ]
    assert scripted_reply(history, TOOLS).text == "Done: hi"


async def test_scripted_adapter_counts_usage():
    reply = await ScriptedAdapter().complete("sys", [ChatMessage(role="user", text="x")], TOOLS)
    assert reply.usage.input_tokens > 0


async def test_fake_openai_server_drives_the_openai_adapter():
    with FakeOpenAIServer() as llm:
        adapter = adapter_for("openai", "scripted", "test-key", base_url=llm.base_url)
        reply = await adapter.complete("sys", [ChatMessage(role="user", text="echo hi")], TOOLS)
        assert reply.tool_calls[0].arguments == {"message": "echo hi"}
        assert llm.requests[0]["model"] == "scripted"
