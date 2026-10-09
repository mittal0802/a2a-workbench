import pytest

from a2a_workbench.core.assistant.keys import ENV_VARS
from a2a_workbench.fixtures.llm import FakeOpenAIServer
from tests.mcp.test_mcp_server import call, connected


@pytest.fixture(autouse=True)
def _no_env_keys(monkeypatch):
    for names in ENV_VARS.values():
        for name in names:
            monkeypatch.delenv(name, raising=False)


async def test_mcp_assist_returns_steps_and_final_text(zoo):
    with FakeOpenAIServer() as llm:
        async with connected() as c:
            names = {t.name for t in (await c.list_tools()).tools}
            assert {"assist", "assistant_providers"} <= names
            providers = await call(c, "assistant_providers")
            assert {p["provider"] for p in providers["providers"]} == {
                "anthropic",
                "openai",
                "gemini",
            }
            out = await call(
                c,
                "assist",
                {
                    "goal": "ask",
                    "agents": [zoo.base_url],
                    "provider": "openai",
                    "model": "scripted",
                },
            )
            assert out["error"]["category"] == "auth"
            from a2a_workbench.core.config import Settings
            from a2a_workbench.core.workbench import Workbench

            async with Workbench.open(Settings()) as wb:
                await wb.provider_keys.put("openai", "sk-mcp-key-1", base_url=llm.base_url)
            out = await call(
                c,
                "assist",
                {
                    "goal": "ask",
                    "agents": [zoo.base_url],
                    "provider": "openai",
                    "model": "scripted",
                },
            )
            assert out["status"] == "idle" and out["final_text"] == "Done: You chose: B"
            assert any(
                s["kind"] == "tool_result" and s["data"]["answered_by"] == "assistant"
                for s in out["steps"]
            )
            follow = await call(c, "assist", {"goal": "echo more", "session_id": out["session_id"]})
            assert follow["final_text"] == "Done: echo more"
