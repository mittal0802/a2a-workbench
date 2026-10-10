import json

import pytest

from a2a_workbench.core.connection.client import interface_override
from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.conversations.parts import TextPartInput
from a2a_workbench.core.errors import AgentCallError
from a2a_workbench.core.health.passive import evaluate
from a2a_workbench.core.tasks.service import ListTasksFilter
from a2a_workbench.fixtures.runner import ZooServer


async def _findings(wb, breaks=(), binding="JSONRPC"):
    """Stream, list and provoke an error on the zoo; return {check_id: [status]}."""
    async with ZooServer(breaks=set(breaks)) as zoo:
        agent = await wb.agents.add(zoo.base_url)
        url = next(
            i["url"] for i in agent.card["supportedInterfaces"] if i["protocolBinding"] == binding
        )
        token = interface_override.set(url)
        try:
            conv = await wb.conversations.create(agent.id)
            [
                e
                async for e in wb.conversations.send(
                    conv.id, [TextPartInput(text="stream")], SendOptions(inherit_ids=False)
                )
            ]
            await wb.tasks.list(agent.id, ListTasksFilter(page_size=5))
            with pytest.raises(AgentCallError):
                await wb.tasks.get(agent.id, "a2aw-missing")
        finally:
            interface_override.reset(token)
        out: dict[str, list[str]] = {}
        for x in await wb.exchanges.list(agent_id=agent.id):
            for f in evaluate(await wb.exchanges.get(x["id"])):
                out.setdefault(f.check_id, []).append(f.status)
        return out


@pytest.mark.parametrize("binding", ["JSONRPC", "HTTP+JSON"])
async def test_compliant_traffic_passes(wb, binding):
    found = await _findings(wb, binding=binding)
    assert set(found) == {"P1.stream_first_event", "P2.list_artifacts_omitted", "P3.error_code"}
    assert all(s == "pass" for statuses in found.values() for s in statuses), found


@pytest.mark.parametrize(
    "brk,check",
    [
        ("stream-status-first", "P1.stream_first_event"),
        ("list-artifacts", "P2.list_artifacts_omitted"),
    ],
)
async def test_detects_violations_in_traffic(wb, brk, check):
    found = await _findings(wb, breaks=[brk])
    assert "fail" in found[check], found


def _record(**kw):
    base = {"url": "http://agent/a2a", "operation": "get_task", "status": 200, "frames": []}
    return {**base, **kw}


def test_error_code_mismatch_is_flagged():
    body = {
        "jsonrpc": "2.0",
        "id": "1",
        "error": {
            "code": -32602,
            "message": "Task not found",
            "data": [
                {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "TASK_NOT_FOUND"}
            ],
        },
    }
    rec = _record(
        request_body=json.dumps({"jsonrpc": "2.0", "method": "GetTask", "params": {"id": "x"}}),
        response_body=json.dumps(body),
    )
    [f] = evaluate(rec)
    assert (f.check_id, f.status) == ("P3.error_code", "fail")
    assert "-32001" in f.expected and "-32602" in f.actual


def test_rest_status_mismatch_is_flagged():
    body = {
        "error": {
            "code": 400,
            "message": "nope",
            "details": [
                {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "TASK_NOT_FOUND"}
            ],
        }
    }
    [f] = evaluate(
        _record(url="http://agent/v1/tasks/x", status=400, response_body=json.dumps(body))
    )
    assert f.status == "fail" and "404" in f.expected


def test_grpc_and_unrelated_exchanges_yield_nothing():
    assert evaluate(_record(url="grpc://agent/lf.a2a.v1.A2AService/GetTask")) == []
    assert evaluate(_record(response_body='{"result": {"id": "t"}}')) == []


def test_message_stream_with_more_events_fails():
    frames = [
        {"t_ms": 1, "data": 'data: {"message": {"messageId": "m"}}'},
        {"t_ms": 2, "data": 'data: {"message": {"messageId": "n"}}'},
    ]
    [f] = evaluate(
        _record(operation="send_message", url="http://agent/v1/message:stream", frames=frames)
    )
    assert f.status == "fail" and "1 more" in f.actual
