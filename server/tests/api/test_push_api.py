import json
import time

from fastapi.testclient import TestClient

from a2a_workbench.api.app import create_app


def _working_task(c, agent_id):
    conv = c.post("/api/conversations", json={"agent_id": agent_id}).json()
    c.post(
        f"/api/conversations/{conv['id']}/messages",
        json={
            "parts": [{"kind": "text", "text": "slow 20"}],
            "options": {"stream": False, "return_immediately": True},
        },
    )
    for _ in range(100):
        events = c.get(f"/api/conversations/{conv['id']}").json()["events"]
        task = next((e["task_id"] for e in events if e["task_id"]), None)
        if task:
            return conv["id"], task
        time.sleep(0.05)
    raise AssertionError("no task")


def test_push_config_api_and_secrets_masked(zoo):
    with TestClient(create_app(), base_url="http://127.0.0.1:8484") as c:
        agent = c.post("/api/agents", json={"url": zoo.base_url}).json()
        _, task = _working_task(c, agent["id"])
        base = f"/api/agents/{agent['id']}/tasks/{task}/push-configs"
        created = c.post(base, json={"webhook": "workbench"}).json()
        hook = created["hook"]
        assert created["config"]["id"] == hook["id"] and hook["url"].endswith(
            f"/hooks/{hook['id']}"
        )
        assert hook["token"] and hook["credentials"]
        custom = c.post(
            base,
            json={
                "webhook": "custom",
                "url": "https://hooks.example/x",
                "token": "my-token-1",
                "auth_scheme": "Bearer",
                "auth_credentials": "my-cred-1",
            },
        ).json()
        listed = c.get(base).json()
        assert {x["id"] for x in listed["configs"]} == {hook["id"], custom["config"]["id"]}
        got = c.get(f"{base}/{hook['id']}").json()
        dump = json.dumps(listed) + json.dumps(got) + json.dumps(custom["config"])
        for secret in (hook["token"], hook["credentials"], "my-token-1", "my-cred-1"):
            assert secret not in dump
        for e in c.get(f"/api/exchanges?agent_id={agent['id']}").json():
            record = json.dumps(c.get(f"/api/exchanges/{e['id']}").json())
            for secret in (hook["token"], hook["credentials"], "my-token-1", "my-cred-1"):
                assert secret not in record
        assert c.delete(f"{base}/{hook['id']}").status_code == 204
        assert c.post(f"/hooks/{hook['id']}", content=b"{}").status_code == 404
        assert [x["id"] for x in c.get(base).json()["configs"]] == [custom["config"]["id"]]
        assert c.get(f"/api/agents/{agent['id']}/push/deliveries").json() == []


def test_public_url_and_tunnel_settings():
    with TestClient(create_app(), base_url="http://127.0.0.1:8484") as c:
        body = c.get("/api/settings/public-url").json()
        assert body["public_base_url"].startswith("http://127.0.0.1:") and body["source"] == "local"
        r = c.put("/api/settings/public-url", json={"public_base_url": "https://hooks.example"})
        assert (
            r.json()["public_base_url"] == "https://hooks.example"
            and r.json()["source"] == "setting"
        )
        assert (
            c.put("/api/settings/public-url", json={"public_base_url": None}).json()["source"]
            == "local"
        )
