import json

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from a2a_workbench.core.assistant.llm import (
    ChatMessage,
    LLMError,
    ToolCall,
    ToolSpec,
    adapter_for,
)
from a2a_workbench.fixtures.runner import free_port
from a2a_workbench.fixtures.serve import ThreadServer


class Canned:
    """A local server answering each POST with the next queued (status, body) reply."""

    def __init__(self):
        self.replies: list[tuple[int, dict]] = []
        self.requests: list[dict] = []

        async def handle(request: Request) -> JSONResponse:
            self.requests.append(
                {"path": request.url.path, "body": json.loads(await request.body())}
            )
            status, body = self.replies.pop(0)
            return JSONResponse(body, status_code=status)

        self.port = free_port()
        self.server = ThreadServer(
            Starlette(routes=[Route("/{path:path}", handle, methods=["POST", "GET"])]),
            port=self.port,
            ready_path="/ready",
        )
        self.url = f"http://127.0.0.1:{self.port}"


@pytest.fixture
def canned():
    c = Canned()
    c.replies.append((200, {}))
    c.server.start()
    c.requests.clear()
    c.replies.clear()
    yield c
    c.server.stop()


TOOLS = [
    ToolSpec(
        name="call_zoo",
        description="Zoo agent",
        input_schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    )
]
HISTORY = [
    ChatMessage(role="user", text="hello"),
    ChatMessage(
        role="assistant",
        text="",
        tool_calls=[ToolCall(id="c1", name="call_zoo", arguments={"message": "hi"})],
    ),
    ChatMessage(
        role="tool", tool_call_id="c1", tool_name="call_zoo", text='{"state": "completed"}'
    ),
]


async def test_anthropic_translation_and_reply(canned):
    canned.replies.append(
        (
            200,
            {
                "id": "m",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5-5",
                "content": [
                    {"type": "text", "text": "ok"},
                    {
                        "type": "tool_use",
                        "id": "c2",
                        "name": "call_zoo",
                        "input": {"message": "again"},
                    },
                ],
                "stop_reason": "tool_use",
                "stop_sequence": None,
                "usage": {"input_tokens": 11, "output_tokens": 7},
            },
        )
    )
    reply = await adapter_for(
        "anthropic", "claude-sonnet-5-5", "sk-ant-secret", base_url=canned.url
    ).complete("SYS", HISTORY, TOOLS)
    assert canned.requests[0]["path"] == "/v1/messages"
    body = canned.requests[0]["body"]
    assert body["system"] == "SYS" and body["tools"][0]["input_schema"]["required"] == ["message"]
    assert body["messages"][1]["content"][0] == {
        "type": "tool_use",
        "id": "c1",
        "name": "call_zoo",
        "input": {"message": "hi"},
    }
    assert body["messages"][2]["content"][0]["type"] == "tool_result"
    assert body["messages"][2]["content"][0]["tool_use_id"] == "c1"
    assert reply.text == "ok" and reply.tool_calls == [
        ToolCall(id="c2", name="call_zoo", arguments={"message": "again"})
    ]
    assert (reply.usage.input_tokens, reply.usage.output_tokens) == (11, 7)


async def test_openai_translation_reply_and_base_url(canned):
    canned.replies.append(
        (
            200,
            {
                "id": "x",
                "object": "chat.completion",
                "created": 1,
                "model": "m",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "c2",
                                    "type": "function",
                                    "function": {
                                        "name": "call_zoo",
                                        "arguments": '{"message": "again"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            },
        )
    )
    reply = await adapter_for("openai", "m", "sk-secret", base_url=canned.url + "/v1").complete(
        "SYS", HISTORY, TOOLS
    )
    assert canned.requests[0]["path"] == "/v1/chat/completions"
    body = canned.requests[0]["body"]
    assert body["messages"][0] == {"role": "system", "content": "SYS"}
    assert body["messages"][2]["tool_calls"][0]["function"]["name"] == "call_zoo"
    assert body["messages"][3] == {
        "role": "tool",
        "tool_call_id": "c1",
        "content": '{"state": "completed"}',
    }
    assert body["tools"][0]["function"]["parameters"]["required"] == ["message"]
    assert reply.tool_calls[0].arguments == {"message": "again"} and reply.usage.output_tokens == 3


async def test_gemini_translation_and_reply(canned):
    canned.replies.append(
        (
            200,
            {
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [
                                {"text": "ok"},
                                {
                                    "functionCall": {
                                        "name": "call_zoo",
                                        "args": {"message": "again"},
                                    }
                                },
                            ],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 4},
            },
        )
    )
    reply = await adapter_for("gemini", "gemini-x", "g-secret", base_url=canned.url).complete(
        "SYS", HISTORY, TOOLS
    )
    assert canned.requests[0]["path"].endswith("/models/gemini-x:generateContent")
    body = canned.requests[0]["body"]
    assert body["systemInstruction"]["parts"][0]["text"] == "SYS"
    assert body["contents"][1]["parts"][0]["functionCall"]["name"] == "call_zoo"
    assert body["contents"][2]["parts"][0]["functionResponse"]["name"] == "call_zoo"
    assert reply.text == "ok" and reply.tool_calls[0].name == "call_zoo"
    assert reply.tool_calls[0].arguments == {"message": "again"} and reply.usage.input_tokens == 9


@pytest.mark.parametrize("provider,suffix", [("anthropic", ""), ("openai", "/v1"), ("gemini", "")])
async def test_auth_error_is_llm_error_without_the_key(canned, provider, suffix):
    canned.replies.append(
        (
            401,
            {
                "error": {
                    "code": 401,
                    "message": "bad key sk-zzz-secret",
                    "status": "UNAUTHENTICATED",
                }
            },
        )
    )
    with pytest.raises(LLMError) as info:
        await adapter_for(provider, "m", "sk-zzz-secret", base_url=canned.url + suffix).complete(
            "SYS", HISTORY, TOOLS
        )
    assert info.value.category == "auth" and "sk-zzz-secret" not in str(info.value)


@pytest.mark.parametrize("provider,suffix", [("anthropic", ""), ("openai", "/v1")])
async def test_wrong_endpoint_names_the_status_and_url(canned, provider, suffix):
    canned.replies.append((404, {"detail": "Not Found"}))
    with pytest.raises(LLMError) as info:
        await adapter_for(provider, "m", "sk-zzz-secret", base_url=canned.url + suffix).complete(
            "SYS", HISTORY, TOOLS
        )
    assert "404" in str(info.value) and canned.url in str(info.value)
    assert info.value.category == "provider" and "sk-zzz-secret" not in str(info.value)


async def test_gemini_thought_signature_round_trips(canned):
    canned.replies.append(
        (
            200,
            {
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [
                                {
                                    "functionCall": {"name": "call_zoo", "args": {"message": "x"}},
                                    "thoughtSignature": "c2lnLTE=",
                                }
                            ],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1},
            },
        )
    )
    adapter = adapter_for("gemini", "gemini-x", "g-secret", base_url=canned.url)
    reply = await adapter.complete("SYS", [ChatMessage(role="user", text="hi")], TOOLS)
    assert reply.tool_calls[0].signature == "c2lnLTE="
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
    history = [
        ChatMessage(role="user", text="hi"),
        ChatMessage(role="assistant", tool_calls=reply.tool_calls),
        ChatMessage(
            role="tool", tool_call_id=reply.tool_calls[0].id, tool_name="call_zoo", text="{}"
        ),
    ]
    await adapter.complete("SYS", history, TOOLS)
    sent = canned.requests[1]["body"]["contents"][1]["parts"][0]
    assert sent["thoughtSignature"] == "c2lnLTE=" and sent["functionCall"]["name"] == "call_zoo"


@pytest.mark.parametrize(
    "provider,suffix,reply",
    [
        (
            "anthropic",
            "",
            {
                "id": "m",
                "type": "message",
                "role": "assistant",
                "model": "m",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        ),
        (
            "gemini",
            "",
            {
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": "ok"}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {},
            },
        ),
        (
            "openai",
            "/v1",
            {
                "id": "x",
                "object": "chat.completion",
                "created": 1,
                "model": "m",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "ok"},
                    }
                ],
            },
        ),
    ],
)
async def test_empty_turns_are_not_sent(canned, provider, suffix, reply):
    canned.replies.append((200, reply))
    history = [
        ChatMessage(role="user", text="hi"),
        ChatMessage(role="assistant", text=""),
        ChatMessage(role="user", text=""),
    ]
    await adapter_for(provider, "m", "k-123456", base_url=canned.url + suffix).complete(
        "SYS", history, TOOLS
    )
    body = canned.requests[0]["body"]
    turns = body.get("messages") or body.get("contents")
    texts = json.dumps(turns)
    assert '"content": []' not in texts and '"parts": []' not in texts
    roles = [t["role"] for t in turns if t["role"] != "system"]
    assert roles == ["user"]
