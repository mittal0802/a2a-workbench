WS = "ws://127.0.0.1:8484/ws"


def _setup(client, zoo):
    agent = client.post("/api/agents", json={"url": zoo.base_url}).json()
    return client.post("/api/conversations", json={"agent_id": agent["id"]}).json()


def test_ws_replays_after_seq_without_duplicates(client, zoo):
    conv = _setup(client, zoo)
    topic = f"conversation:{conv['id']}"
    with client.websocket_connect(WS) as ws:
        ws.send_json({"op": "subscribe", "topic": topic, "after_seq": 0})
        client.post(
            f"/api/conversations/{conv['id']}/messages",
            json={"parts": [{"kind": "text", "text": "stream"}]},
        )
        seen = []
        while not seen or seen[-1]["data"].get("state") != "completed":
            msg = ws.receive_json()
            assert msg["topic"] == topic and msg["type"] == "event"
            seen.append(msg["event"])
    assert [e["seq"] for e in seen] == list(range(1, len(seen) + 1))
    with client.websocket_connect(WS) as ws:
        ws.send_json({"op": "subscribe", "topic": topic, "after_seq": 3})
        replay = [ws.receive_json()["event"]["seq"] for _ in range(len(seen) - 3)]
    assert replay == list(range(4, len(seen) + 1))


def test_ws_exchange_topic_receives_summaries(client, zoo):
    conv = _setup(client, zoo)
    with client.websocket_connect(WS) as ws:
        ws.send_json({"op": "subscribe", "topic": f"exchanges:{conv['id']}"})
        client.post(
            f"/api/conversations/{conv['id']}/messages",
            json={"parts": [{"kind": "text", "text": "echo hi"}]},
        )
        msg = ws.receive_json()
    assert msg["type"] == "exchange" and msg["exchange"]["operation"] == "send_message"


def test_ws_rejects_unknown_op(client):
    with client.websocket_connect(WS) as ws:
        ws.send_json({"op": "dance"})
        assert ws.receive_json()["type"] == "error"


def test_ws_rejects_unknown_topic(client):
    with client.websocket_connect(WS) as ws:
        ws.send_json({"op": "subscribe", "topic": "secrets:all"})
        assert ws.receive_json()["type"] == "error"
