import json
import time

import pytest
from fastapi.testclient import TestClient

from a2a_workbench.api.app import create_app
from a2a_workbench.core.assistant.keys import ENV_VARS
from a2a_workbench.fixtures.llm import FakeOpenAIServer

WS = "ws://127.0.0.1:8484/ws"


@pytest.fixture(autouse=True)
def _no_env_keys(monkeypatch):
    for names in ENV_VARS.values():
        for name in names:
            monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="module")
def llm():
    with FakeOpenAIServer() as server:
        yield server


@pytest.fixture
def c():
    with TestClient(create_app(), base_url="http://127.0.0.1:8484") as client:
        yield client


def _setup(c, llm, zoo, **session):
    r = c.put(
        "/api/assistant/providers/openai",
        json={"api_key": "sk-test-key-0001", "base_url": llm.base_url},
    )
    assert r.status_code == 200, r.text
    agent = c.post("/api/agents", json={"url": zoo.base_url}).json()
    r = c.post(
        "/api/assistant/sessions",
        json={"provider": "openai", "model": "scripted", "agent_ids": [agent["id"]], **session},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _wait(c, sid, status=("idle", "awaiting_user", "awaiting_sign_in", "stopped"), timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = c.get(f"/api/assistant/sessions/{sid}").json()
        if body["session"]["status"] in status and body["steps"]:
            return body
        time.sleep(0.1)
    raise AssertionError(f"session stuck: {body}")


def test_providers_are_masked(c):
    assert {p["provider"] for p in c.get("/api/assistant/providers").json()} == {
        "anthropic",
        "openai",
        "gemini",
    }
    r = c.put("/api/assistant/providers/anthropic", json={"api_key": "sk-ant-very-secret-77"})
    assert r.json()["preview"] == "••••t-77" and "very-secret" not in r.text
    assert "very-secret" not in c.get("/api/assistant/providers").text
    assert c.delete("/api/assistant/providers/anthropic").status_code == 204
    assert c.put("/api/assistant/providers/nope", json={"api_key": "x"}).status_code == 422


def test_session_lifecycle_over_api_and_ws(c, llm, zoo):
    s = _setup(c, llm, zoo)
    with c.websocket_connect(WS) as ws:
        ws.send_json({"op": "subscribe", "topic": f"assistant:{s['id']}", "after_seq": 0})
        assert (
            c.post(f"/api/assistant/sessions/{s['id']}/messages", json={"text": "ask"}).status_code
            == 202
        )
        kinds = []
        while "done" not in kinds:
            msg = ws.receive_json()
            assert msg["topic"] == f"assistant:{s['id']}" and msg["type"] == "step"
            kinds.append(msg["step"]["kind"])
    body = _wait(c, s["id"])
    assert body["steps"][-1]["data"]["text"] == "Done: You chose: B"
    assert [st["kind"] for st in body["steps"]] == kinds
    assert any(x["id"] == s["id"] for x in c.get("/api/assistant/sessions").json())
    r = c.patch(f"/api/assistant/sessions/{s['id']}", json={"response_mode": "pass_through"})
    assert r.json()["response_mode"] == "pass_through"


def test_ws_replays_steps_after_seq(c, llm, zoo):
    s = _setup(c, llm, zoo)
    c.post(f"/api/assistant/sessions/{s['id']}/messages", json={"text": "echo hi"})
    steps = _wait(c, s["id"])["steps"]
    with c.websocket_connect(WS) as ws:
        ws.send_json({"op": "subscribe", "topic": f"assistant:{s['id']}", "after_seq": 1})
        replayed = [ws.receive_json()["step"]["seq"] for _ in range(len(steps) - 1)]
    assert replayed == [st["seq"] for st in steps[1:]]


def test_pass_through_reply_and_stop(c, llm, zoo):
    s = _setup(c, llm, zoo, response_mode="pass_through")
    c.post(f"/api/assistant/sessions/{s['id']}/messages", json={"text": "ask"})
    body = _wait(c, s["id"])
    assert body["session"]["status"] == "awaiting_user", [
        (st["kind"], st["data"]) for st in body["steps"]
    ]
    assert body["session"]["pending"]["question"] == "Which option should I pick: A or B?"
    assert c.post(f"/api/assistant/sessions/{s['id']}/stop").status_code == 204
    assert _wait(c, s["id"], status=("stopped",))["steps"][-1]["data"]["limit"] == "stopped"


def test_session_api_never_returns_the_key(c, llm, zoo):
    s = _setup(c, llm, zoo)
    c.post(f"/api/assistant/sessions/{s['id']}/messages", json={"text": "echo hi"})
    body = _wait(c, s["id"])
    dump = json.dumps(body) + json.dumps(c.get("/api/assistant/sessions").json())
    for e in c.get(f"/api/exchanges?agent_id={s['agent_ids'][0]}").json():
        dump += json.dumps(c.get(f"/api/exchanges/{e['id']}").json())
    assert "sk-test-key-0001" not in dump


def test_errors(c, llm, zoo):
    assert c.get("/api/assistant/sessions/nope").status_code == 404
    r = c.post("/api/assistant/sessions", json={"provider": "openai", "agent_ids": []})
    assert r.status_code == 422
    assert (
        c.post(
            "/api/assistant/sessions",
            json={"provider": "openai", "model": "m", "agent_ids": ["missing"]},
        ).status_code
        == 404
    )
