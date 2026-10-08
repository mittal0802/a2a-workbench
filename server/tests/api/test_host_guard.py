import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from a2a_workbench.api.app import create_app
from a2a_workbench.core.config import Settings

WS = "ws://127.0.0.1:8484/ws"


def test_rejects_foreign_host_header(client):
    assert client.get("/api/agents", headers={"host": "evil.example"}).status_code == 400


def test_accepts_loopback_hosts(client):
    for host in ("127.0.0.1:8484", "localhost:8484", "[::1]:8484"):
        assert client.get("/api/health", headers={"host": host}).status_code == 200


def test_ws_rejects_foreign_origin(client):
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/ws", headers={"origin": "https://evil.example"}) as ws,
    ):
        ws.send_json({"op": "dance"})
        ws.receive_json()


def test_ws_accepts_same_host_origin(client):
    with client.websocket_connect(WS, headers={"origin": "http://localhost:8484"}) as ws:
        ws.send_json({"op": "dance"})
        assert ws.receive_json()["type"] == "error"


def test_allowed_hosts_setting_extends_the_list(monkeypatch):
    monkeypatch.setenv("A2AW_ALLOWED_HOSTS", "workbench.lan")
    with TestClient(create_app(Settings()), base_url="http://127.0.0.1:8484") as c:
        assert c.get("/api/health", headers={"host": "workbench.lan:8484"}).status_code == 200
        assert c.get("/api/health", headers={"host": "other.lan"}).status_code == 400
