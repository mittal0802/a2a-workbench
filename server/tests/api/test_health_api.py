import json
import time

import pytest
from fastapi.testclient import TestClient

from a2a_workbench.api.app import create_app
from a2a_workbench.fixtures.auth import ZOO_SECRETS
from a2a_workbench.fixtures.runner import ZooServer


def _wait_done(c, run_id, attempts=600):
    for _ in range(attempts):
        run = c.get(f"/api/health/runs/{run_id}").json()
        if run["status"] != "running":
            return run
        time.sleep(0.1)
    raise AssertionError("run did not finish")


def test_run_lifecycle_and_reports(client, zoo):
    agent = client.post("/api/agents", json={"url": zoo.base_url}).json()
    started = client.post(f"/api/agents/{agent['id']}/health/runs", json={"areas": ["A", "F"]})
    assert started.status_code == 202
    run_id = started.json()["run_id"]
    assert started.json()["topic"] == f"health-run:{run_id}"
    run = _wait_done(client, run_id)
    assert run["status"] == "done" and run["score"] == 100
    assert {r["area"] for r in run["results"]} == {"A", "F"}
    listed = client.get("/api/health/runs", params={"agent_id": agent["id"]}).json()
    assert [r["id"] for r in listed] == [run_id]
    report = client.get(f"/api/health/runs/{run_id}/report.json")
    assert "attachment" in report.headers["content-disposition"]
    body = report.json()
    assert body["schema"] == 1 and body["score"] == 100
    html = client.get(f"/api/health/runs/{run_id}/report.html")
    assert html.headers["content-type"].startswith("text/html") and "<html" in html.text.lower()


def test_run_rejects_unknown_area_and_agent(client, zoo):
    agent = client.post("/api/agents", json={"url": zoo.base_url}).json()
    bad = client.post(f"/api/agents/{agent['id']}/health/runs", json={"areas": ["Z"]})
    assert bad.status_code == 422
    assert client.post("/api/agents/nope/health/runs", json={}).status_code == 404
    assert client.get("/api/health/runs/nope").status_code == 404
    bad_faults = client.post(f"/api/agents/{agent['id']}/health/runs", json={"faults": "nonsense"})
    assert bad_faults.status_code == 422


def test_check_catalogue(client):
    body = client.get("/api/health/checks").json()
    ids = {c["id"] for c in body["checks"]}
    assert {"A1.card_reachable", "K1.errors_mapping", "L3.resilience_multi_stream"} <= ids
    assert body["areas"]["H"] == "Push notifications"


def test_ws_streams_run_progress(client, zoo):
    agent = client.post("/api/agents", json={"url": zoo.base_url}).json()
    with client.websocket_connect("ws://127.0.0.1:8484/ws") as ws:
        run_id = client.post(
            f"/api/agents/{agent['id']}/health/runs", json={"areas": ["F"]}
        ).json()["run_id"]
        ws.send_json({"op": "subscribe", "topic": f"health-run:{run_id}"})
        kinds = []
        while "finished" not in kinds:
            msg = ws.receive_json()
            assert msg["topic"] == f"health-run:{run_id}"
            kinds.append(msg["event"]["kind"])
    assert "result" in kinds


def test_exchange_checks(client, zoo):
    agent = client.post("/api/agents", json={"url": zoo.base_url}).json()
    client.get(f"/api/agents/{agent['id']}/tasks", params={"page_size": 5})
    exchanges = client.get("/api/exchanges", params={"agent_id": agent["id"]}).json()
    listing = next(x for x in exchanges if x["operation"] == "list_tasks")
    checks = client.get(f"/api/exchanges/{listing['id']}").json()["checks"]
    assert [(c["check_id"], c["status"]) for c in checks] == [("P2.list_artifacts_omitted", "pass")]


@pytest.fixture
def bearer_zoo():
    with ZooServer(auth="bearer", grpc=False) as zoo:
        yield zoo


def test_report_evidence_and_secrets(bearer_zoo):
    with TestClient(create_app(), base_url="http://127.0.0.1:8484") as c:
        agent = c.post("/api/agents", json={"url": bearer_zoo.base_url}).json()
        c.put(
            f"/api/agents/{agent['id']}/credentials/bearer",
            json={"kind": "http_bearer", "token": ZOO_SECRETS["token"]},
        )
        run_id = c.post(
            f"/api/agents/{agent['id']}/health/runs", json={"areas": ["C", "F", "I"]}
        ).json()["run_id"]
        run = _wait_done(c, run_id)
        probed = [r for r in run["results"] if r["status"] != "not_supported"]
        assert probed and all(r["exchange_ids"] for r in probed), [
            r["check_id"] for r in probed if not r["exchange_ids"]
        ]
        texts = [
            c.get(f"/api/health/runs/{run_id}/report.json").text,
            c.get(f"/api/health/runs/{run_id}/report.html").text,
        ]
        for r in probed:
            for eid in r["exchange_ids"]:
                texts.append(json.dumps(c.get(f"/api/exchanges/{eid}").json()))
        assert all(ZOO_SECRETS["token"] not in t for t in texts)


def test_stopping_a_run_that_is_not_active_is_a_conflict(client, zoo):
    agent = client.post("/api/agents", json={"url": zoo.base_url}).json()
    run_id = client.post(f"/api/agents/{agent['id']}/health/runs", json={"areas": ["A"]}).json()[
        "run_id"
    ]
    _wait_done(client, run_id)
    assert client.delete(f"/api/health/runs/{run_id}/active").status_code == 409
