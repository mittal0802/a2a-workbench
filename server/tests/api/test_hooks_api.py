import json

from fastapi.testclient import TestClient

from a2a_workbench.api.app import create_app


def test_hooks_accept_foreign_hosts_but_only_with_credentials(zoo):
    with TestClient(create_app(), base_url="http://127.0.0.1:8484") as c:
        wb = c.app.state.workbench
        agent = c.post("/api/agents", json={"url": zoo.base_url}).json()
        hook = c.portal.call(lambda: wb.hooks.create(agent["id"], task_id="t-1"))
        body = json.dumps(
            {
                "statusUpdate": {
                    "taskId": "t-1",
                    "contextId": "x",
                    "status": {"state": "TASK_STATE_WORKING"},
                }
            }
        )
        foreign = {"host": "abc.trycloudflare.com", "content-type": "application/json"}
        denied = c.post(f"/hooks/{hook.id}", content=body, headers=foreign)
        assert denied.status_code == 401
        ok = c.post(
            f"/hooks/{hook.id}",
            content=body,
            headers={
                **foreign,
                "authorization": f"Bearer {hook.credentials}",
                "x-a2a-notification-token": hook.token,
            },
        )
        assert ok.status_code == 200 and ok.json()["verdict"] == "accepted"
        assert c.post("/hooks/nope", content=body, headers=foreign).status_code == 404
        assert c.get("/api/agents", headers={"host": "abc.trycloudflare.com"}).status_code == 400
        assert c.get(f"/hooks/{hook.id}", headers=foreign).status_code in (400, 405)
