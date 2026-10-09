import json

from a2a_workbench.core.assistant.service import AssistantService, SessionIn
from a2a_workbench.fixtures.llm import FakeOpenAIServer
from tests.core.assistant.test_llm_adapters import HISTORY, TOOLS, Canned, canned  # noqa: F401


async def test_llm_calls_are_recorded_with_the_key_masked(wb, zoo):
    with FakeOpenAIServer() as llm:
        await wb.provider_keys.put("openai", "sk-record-me-0042", base_url=llm.base_url)
        svc = AssistantService(wb)
        agent = await wb.agents.add(zoo.base_url)
        s = await svc.create(SessionIn(provider="openai", model="scripted", agent_ids=[agent.id]))
        steps = [st async for st in svc.send(s.id, "echo hi")]
        await svc.close()
    calls = await wb.exchanges.list(conversation_id=s.id)
    assert [c["operation"] for c in calls] == ["llm_call", "llm_call"]
    first = await wb.exchanges.get(calls[0]["id"])
    assert first["url"].endswith("/v1/chat/completions") and first["status"] == 200
    assert json.loads(first["request_body"])["messages"][1]["content"] == "echo hi"
    assert "choices" in json.loads(first["response_body"])
    assert first["request_headers"]["authorization"] == "••••"
    assert "sk-record-me-0042" not in json.dumps([await wb.exchanges.get(c["id"]) for c in calls])
    assistant_steps = [st for st in steps if st.kind == "assistant"]
    assert [st.data["exchange_id"] for st in assistant_steps] == [c["id"] for c in calls]


async def test_failed_llm_call_is_recorded(wb, canned):  # noqa: F811
    from a2a_workbench.core.assistant.llm import LLMError, adapter_for
    from a2a_workbench.core.assistant.recording import LLMRecorder

    canned.replies.append((401, {"error": {"message": "bad key"}}))
    recorder = LLMRecorder(wb.exchanges, session_id="sess1")
    try:
        await adapter_for(
            "anthropic", "m", "sk-ant-secret-9", base_url=canned.url, recorder=recorder
        ).complete("SYS", HISTORY, TOOLS)
    except LLMError:
        pass
    record = await wb.exchanges.get(recorder.last_id)
    assert record["status"] == 401 and record["request_headers"]["x-api-key"] == "••••"
    assert "sk-ant-secret-9" not in json.dumps(record)


async def test_gemini_key_header_is_masked(wb, canned):  # noqa: F811
    from a2a_workbench.core.assistant.llm import adapter_for
    from a2a_workbench.core.assistant.recording import LLMRecorder

    canned.replies.append(
        (
            200,
            {
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": "ok"}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {},
            },
        )
    )
    recorder = LLMRecorder(wb.exchanges, session_id="sess2")
    await adapter_for(
        "gemini", "g", "g-secret-key-77", base_url=canned.url, recorder=recorder
    ).complete("SYS", HISTORY, TOOLS)
    record = await wb.exchanges.get(recorder.last_id)
    assert "g-secret-key-77" not in json.dumps(record) and record["response_body"]
