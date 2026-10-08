import json
from contextlib import asynccontextmanager

from mcp.client.client import Client

from a2a_workbench.core.config import Settings
from a2a_workbench.core.workbench import Workbench
from a2a_workbench.mcp.server import build_mcp_server


@asynccontextmanager
async def connected():
    async with Workbench.open(Settings()) as wb, Client(build_mcp_server(wb)) as client:
        yield client


async def call(client, name, args=None):
    result = await client.call_tool(name, args or {})
    return json.loads(result.content[0].text)


async def test_tools_are_listed_with_descriptions():
    async with connected() as mcp_client:
        await _test_tools_are_listed_with_descriptions(mcp_client)


async def _test_tools_are_listed_with_descriptions(mcp_client):
    tools = {t.name: t for t in (await mcp_client.list_tools()).tools}
    expected = {
        "list_agents",
        "add_agent",
        "fetch_card",
        "send_message",
        "get_task",
        "list_tasks",
        "cancel_task",
        "subscribe_task",
        "resubscribe",
        "check_status",
        "list_exchanges",
        "get_exchange",
        "fault_presets",
    }
    assert expected <= set(tools)
    assert all(tools[n].description for n in expected)


async def test_send_message_and_inspect_traffic(zoo):
    async with connected() as mcp_client:
        await _test_send_message_and_inspect_traffic(mcp_client, zoo)


async def _test_send_message_and_inspect_traffic(mcp_client, zoo):
    body = await call(mcp_client, "send_message", {"agent": zoo.base_url, "text": "stream"})
    assert body["final_state"] == "completed" and body["error"] is None
    assert body["events"][0]["kind"] == "user_message"
    listed = await call(mcp_client, "list_exchanges", {"conversation_id": body["conversation_id"]})
    exchanges = listed["exchanges"]
    assert exchanges[-1]["operation"] == "send_message"
    detail = await call(mcp_client, "get_exchange", {"exchange_id": exchanges[-1]["id"]})
    assert detail["frames"]


async def test_continue_conversation_answers_question(zoo):
    async with connected() as mcp_client:
        await _test_continue_conversation_answers_question(mcp_client, zoo)


async def _test_continue_conversation_answers_question(mcp_client, zoo):
    first = await call(mcp_client, "send_message", {"agent": zoo.base_url, "text": "ask"})
    assert first["final_state"] == "input_required"
    second = await call(
        mcp_client,
        "send_message",
        {"agent": zoo.base_url, "text": "A", "conversation_id": first["conversation_id"]},
    )
    assert second["final_state"] == "completed"


async def test_task_tools(zoo):
    async with connected() as mcp_client:
        await _test_task_tools(mcp_client, zoo)


async def _test_task_tools(mcp_client, zoo):
    sent = await call(
        mcp_client, "send_message", {"agent": zoo.base_url, "text": "echo t", "stream": False}
    )
    task_id = sent["events"][-1]["task_id"]
    got = await call(mcp_client, "get_task", {"agent": zoo.base_url, "task_id": task_id})
    assert got["state"] == "completed"
    listed = await call(mcp_client, "list_tasks", {"agent": zoo.base_url, "status": "completed"})
    assert task_id in [t["id"] for t in listed["tasks"]]
    cancel = await call(mcp_client, "cancel_task", {"agent": zoo.base_url, "task_id": task_id})
    assert cancel["error"]["reason"] == "TASK_NOT_CANCELABLE"


async def test_faults_and_recovery_tools(zoo):
    async with connected() as mcp_client:
        await _test_faults_and_recovery_tools(mcp_client, zoo)


async def _test_faults_and_recovery_tools(mcp_client, zoo):
    presets = (await call(mcp_client, "fault_presets"))["presets"]
    assert "flaky_stream" in [p["name"] for p in presets]
    lost = await call(
        mcp_client,
        "send_message",
        {"agent": zoo.base_url, "text": "long", "faults": "flaky_stream"},
    )
    assert lost["events"][-1]["kind"] == "connection_lost"
    rec = await call(mcp_client, "resubscribe", {"conversation_id": lost["conversation_id"]})
    assert rec["events"][-1]["kind"] == "recovered"
    assert rec["events"][-1]["data"]["snapshot_first"] is True


async def test_fetch_card_and_errors_are_structured(zoo):
    async with connected() as mcp_client:
        await _test_fetch_card_and_errors_are_structured(mcp_client, zoo)


async def _test_fetch_card_and_errors_are_structured(mcp_client, zoo):
    card = await call(mcp_client, "fetch_card", {"target": zoo.base_url})
    assert card["card"]["name"] == "Zoo agent"
    ext = await call(mcp_client, "fetch_card", {"target": zoo.base_url, "extended": True})
    assert any(d["path"] == "skills[visa]" for d in ext["diff"])
    bad = await call(mcp_client, "fetch_card", {"target": "http://127.0.0.1:1"})
    assert bad["error"]["category"] == "transport"


async def test_cli_mcp_command_serves_over_stdio(tmp_path):
    import os
    import sys
    from pathlib import Path

    from mcp import StdioServerParameters

    exe = Path(sys.executable).parent / "a2a-workbench"
    params = StdioServerParameters(
        command=str(exe), args=["mcp"], env={**os.environ, "A2AW_HOME": str(tmp_path)}
    )
    async with Client(params) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        presets = json.loads((await client.call_tool("fault_presets", {})).content[0].text)
    assert "send_message" in names and len(presets["presets"]) == 6


async def test_subscribe_task_times_out_with_partial_events(zoo):
    import time

    async with connected() as mcp_client:
        sent = await call(
            mcp_client,
            "send_message",
            {
                "agent": zoo.base_url,
                "text": "stall 10",
                "stream": False,
                "return_immediately": True,
            },
        )
        task_id = sent["events"][-1]["task_id"]
        start = time.monotonic()
        out = await call(
            mcp_client,
            "subscribe_task",
            {"agent": zoo.base_url, "task_id": task_id, "timeout_s": 1},
        )
        assert time.monotonic() - start < 4
        assert out["timed_out"] is True and out["events"][0]["kind"] == "task"


async def test_send_message_times_out(zoo):
    async with connected() as mcp_client:
        out = await call(
            mcp_client, "send_message", {"agent": zoo.base_url, "text": "stall 10", "timeout_s": 1}
        )
        assert out["timed_out"] is True and out["conversation_id"]


async def test_send_message_unknown_conversation_returns_error(zoo):
    async with connected() as mcp_client:
        out = await call(
            mcp_client,
            "send_message",
            {"agent": zoo.base_url, "text": "x", "conversation_id": "nope"},
        )
        assert out["error"]["category"] == "workbench"
