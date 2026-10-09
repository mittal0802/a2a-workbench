from fastapi.testclient import TestClient

from a2a_workbench.api.app import create_app


def test_integration_endpoint(zoo):
    with TestClient(create_app(), base_url="http://127.0.0.1:8484") as c:
        agent = c.post("/api/agents", json={"url": zoo.base_url}).json()
        body = c.get(f"/api/agents/{agent['id']}/integration").json()
        assert body["card_url"] == f"{zoo.base_url}/.well-known/agent-card.json"
        assert set(body["snippets"]) == {"sdk", "adk", "langgraph", "openai", "claude"}
        assert "call_agent" in body["snippets"]["sdk"]["code"] and body["guidance"]
        assert c.get("/api/agents/nope/integration").status_code == 404
