def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["version"]


def test_preview_then_add_then_list(client, zoo):
    preview = client.post("/api/cards/preview", json={"url": zoo.base_url}).json()
    assert preview["card"]["name"] == "Zoo agent"
    assert preview["signature_status"] == "verified"
    assert preview["default_interface_url"].endswith("/a2a")
    r = client.post("/api/agents", json={"url": zoo.base_url})
    assert r.status_code == 201
    agent = r.json()
    assert client.get("/api/agents").json()[0]["id"] == agent["id"]
    assert client.get(f"/api/agents/{agent['id']}").json()["name"] == "Zoo agent"
    assert client.post("/api/agents", json={"url": zoo.base_url}).status_code == 409


def test_add_agent_unreachable_returns_422(client):
    r = client.post("/api/agents", json={"url": "http://127.0.0.1:1"})
    assert r.status_code == 422
    assert r.json()["error"]["category"] == "transport"


def test_preview_not_an_agent_returns_422_protocol(client, zoo):
    r = client.post("/api/cards/preview", json={"url": f"{zoo.base_url}/missing/card.json"})
    assert r.status_code == 422
    assert r.json()["error"]["category"] == "protocol"


def test_patch_interface_refresh_and_delete(client, zoo):
    agent = client.post("/api/agents", json={"url": zoo.base_url}).json()
    r = client.patch(
        f"/api/agents/{agent['id']}", json={"selected_interface_url": f"{zoo.base_url}/v1"}
    )
    assert r.json()["selected_interface_url"].endswith("/v1")
    bad = client.patch(f"/api/agents/{agent['id']}", json={"selected_interface_url": "x"})
    assert bad.status_code == 422
    assert client.post(f"/api/agents/{agent['id']}/refresh").status_code == 200
    assert client.delete(f"/api/agents/{agent['id']}").status_code == 204
    assert client.get(f"/api/agents/{agent['id']}").status_code == 404
