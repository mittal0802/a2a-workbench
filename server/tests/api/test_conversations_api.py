import time


def _wait_for(client, conv_id, predicate, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/conversations/{conv_id}").json()
        if predicate(body["events"]):
            return body
        time.sleep(0.05)
    raise AssertionError("condition not met")


def _agent_and_conv(client, zoo):
    agent = client.post("/api/agents", json={"url": zoo.base_url}).json()
    conv = client.post("/api/conversations", json={"agent_id": agent["id"]}).json()
    return agent, conv


def test_send_message_runs_in_background(client, zoo):
    agent, conv = _agent_and_conv(client, zoo)
    r = client.post(
        f"/api/conversations/{conv['id']}/messages",
        json={"parts": [{"kind": "text", "text": "stream"}], "options": {"stream": True}},
    )
    assert r.status_code == 202
    body = _wait_for(
        client, conv["id"], lambda ev: ev and ev[-1].get("data", {}).get("state") == "completed"
    )
    assert body["conversation"]["title"] == "stream"
    listed = client.get(f"/api/agents/{agent['id']}/conversations").json()
    assert [c["id"] for c in listed] == [conv["id"]]
    ex = client.get("/api/exchanges", params={"conversation_id": conv["id"]}).json()
    assert ex[-1]["operation"] == "send_message"
    full = client.get(f"/api/exchanges/{ex[-1]['id']}").json()
    assert full["frames"] and full["request_headers"]["a2a-version"] == "1.0"


def test_cancel_endpoint(client, zoo):
    _, conv = _agent_and_conv(client, zoo)
    client.post(
        f"/api/conversations/{conv['id']}/messages",
        json={
            "parts": [{"kind": "text", "text": "slow 30"}],
            "options": {"stream": False, "return_immediately": True},
        },
    )
    _wait_for(client, conv["id"], lambda ev: any(e["kind"] == "task" for e in ev))
    assert client.post(f"/api/conversations/{conv['id']}/cancel").status_code == 202
    _wait_for(client, conv["id"], lambda ev: ev[-1]["data"].get("state") == "canceled")


def test_invalid_part_is_422(client, zoo):
    _, conv = _agent_and_conv(client, zoo)
    r = client.post(f"/api/conversations/{conv['id']}/messages", json={"parts": [{"kind": "file"}]})
    assert r.status_code == 422


def test_empty_parts_is_422(client, zoo):
    _, conv = _agent_and_conv(client, zoo)
    r = client.post(f"/api/conversations/{conv['id']}/messages", json={"parts": []})
    assert r.status_code == 422


def test_unknown_conversation_is_404(client):
    assert client.get("/api/conversations/nope").status_code == 404
    assert client.post("/api/conversations", json={"agent_id": "nope"}).status_code == 404


def test_resubscribe_and_check_status_endpoints(client, zoo):
    _, conv = _agent_and_conv(client, zoo)
    drop = {"rules": [{"kind": "drop_stream", "params": {"after_events": 3}}]}
    client.post(
        f"/api/conversations/{conv['id']}/messages",
        json={"parts": [{"kind": "text", "text": "long"}], "options": {"faults": drop}},
    )
    _wait_for(client, conv["id"], lambda ev: ev and ev[-1]["kind"] == "connection_lost")
    assert client.post(f"/api/conversations/{conv['id']}/resubscribe", json={}).status_code == 202
    body = _wait_for(client, conv["id"], lambda ev: ev[-1]["kind"] == "recovered")
    assert body["events"][-1]["data"]["snapshot_first"] is True
    assert client.post(f"/api/conversations/{conv['id']}/check-status").status_code == 202
    _wait_for(client, conv["id"], lambda ev: ev[-1]["data"].get("method") == "get_task")


def test_send_with_invalid_fault_profile_is_422(client, zoo):
    _, conv = _agent_and_conv(client, zoo)
    r = client.post(
        f"/api/conversations/{conv['id']}/messages",
        json={
            "parts": [{"kind": "text", "text": "x"}],
            "options": {"faults": {"rules": [{"kind": "nope"}]}},
        },
    )
    assert r.status_code == 422
