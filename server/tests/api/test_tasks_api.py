def _agent_with_task(client, zoo):
    import time

    agent = client.post("/api/agents", json={"url": zoo.base_url}).json()
    conv = client.post("/api/conversations", json={"agent_id": agent["id"]}).json()
    client.post(
        f"/api/conversations/{conv['id']}/messages",
        json={"parts": [{"kind": "text", "text": "echo x"}], "options": {"stream": False}},
    )
    for _ in range(100):
        body = client.get(f"/api/conversations/{conv['id']}").json()
        if body["conversation"]["task_state"] == "completed":
            return agent, body["conversation"]
        time.sleep(0.05)
    raise AssertionError("task did not complete")


def test_list_get_cancel_tasks(client, zoo):
    agent, conv = _agent_with_task(client, zoo)
    listed = client.get(
        f"/api/agents/{agent['id']}/tasks",
        params={"context_id": conv["context_id"], "status": "completed", "page_size": 10},
    ).json()
    assert [t["id"] for t in listed["tasks"]] == [conv["task_id"]]
    one = client.get(
        f"/api/agents/{agent['id']}/tasks/{conv['task_id']}", params={"history_length": 1}
    )
    assert one.json()["state"] == "completed"
    r = client.post(f"/api/agents/{agent['id']}/tasks/{conv['task_id']}/cancel", json={})
    assert r.status_code == 422 and r.json()["error"]["reason"] == "TASK_NOT_CANCELABLE"


def test_unknown_task_is_422_with_reason(client, zoo):
    agent = client.post("/api/agents", json={"url": zoo.base_url}).json()
    r = client.get(f"/api/agents/{agent['id']}/tasks/nope")
    assert r.status_code == 422 and r.json()["error"]["reason"] == "TASK_NOT_FOUND"


def test_bad_status_filter_is_422(client, zoo):
    agent = client.post("/api/agents", json={"url": zoo.base_url}).json()
    assert (
        client.get(f"/api/agents/{agent['id']}/tasks", params={"status": "bogus"}).status_code
        == 422
    )


def test_watch_task_resubscribes_in_a_conversation(client, zoo):
    import time

    agent = client.post("/api/agents", json={"url": zoo.base_url}).json()
    conv = client.post("/api/conversations", json={"agent_id": agent["id"]}).json()
    client.post(
        f"/api/conversations/{conv['id']}/messages",
        json={"parts": [{"kind": "text", "text": "long"}], "options": {"stream": False, "return_immediately": True}},
    )
    for _ in range(100):
        task_id = client.get(f"/api/conversations/{conv['id']}").json()["conversation"]["task_id"]
        if task_id:
            break
        time.sleep(0.05)
    r = client.post(f"/api/agents/{agent['id']}/tasks/{task_id}/watch")
    assert r.status_code == 200 and r.json()["conversation_id"] == conv["id"]
    for _ in range(200):
        events = client.get(f"/api/conversations/{conv['id']}").json()["events"]
        if events and events[-1]["kind"] == "recovered":
            break
        time.sleep(0.05)
    assert events[-1]["kind"] == "recovered" and events[-1]["data"]["state_after"] == "completed"
