import pytest
from fastapi.testclient import TestClient

from a2a_workbench.api.app import create_app
from a2a_workbench.fixtures.auth import ZOO_SECRETS
from a2a_workbench.fixtures.runner import ZooServer


@pytest.fixture(scope="module")
def bearer_zoo():
    with ZooServer(auth="bearer", grpc=False) as zoo:
        yield zoo


@pytest.fixture
def c():
    with TestClient(create_app(), base_url="http://127.0.0.1:8484") as client:
        yield client


def test_security_overview_and_credential_round_trip(c, bearer_zoo):
    agent = c.post("/api/agents", json={"url": bearer_zoo.base_url}).json()
    sec = c.get(f"/api/agents/{agent['id']}/security").json()
    assert sec["status"] == "sign_in_needed" and sec["missing"] == ["bearer"]
    scheme = sec["schemes"][0]
    assert (scheme["name"], scheme["type"], scheme["label"]) == ("bearer", "http", "Bearer token")
    assert scheme["credential"] is None
    r = c.put(
        f"/api/agents/{agent['id']}/credentials/bearer",
        json={"kind": "http_bearer", "token": ZOO_SECRETS["token"]},
    )
    assert r.status_code == 200 and ZOO_SECRETS["token"] not in r.text
    sec = c.get(f"/api/agents/{agent['id']}/security").json()
    assert sec["status"] == "signed_in" and sec["schemes"][0]["credential"]["preview"].startswith(
        "••••"
    )
    assert ZOO_SECRETS["token"] not in c.get(f"/api/agents/{agent['id']}/security").text
    assert c.delete(f"/api/agents/{agent['id']}/credentials/bearer").status_code == 204
    assert c.get(f"/api/agents/{agent['id']}/security").json()["status"] == "sign_in_needed"


def test_open_agent_needs_no_sign_in(c, zoo):
    agent = c.post("/api/agents", json={"url": zoo.base_url}).json()
    assert c.get(f"/api/agents/{agent['id']}/security").json()["status"] == "not_required"


def test_unknown_scheme_or_bad_credential_is_422(c, bearer_zoo):
    agent = c.post("/api/agents", json={"url": bearer_zoo.base_url}).json()
    assert (
        c.put(
            f"/api/agents/{agent['id']}/credentials/nope",
            json={"kind": "http_bearer", "token": "x"},
        ).status_code
        == 422
    )
    assert (
        c.put(
            f"/api/agents/{agent['id']}/credentials/bearer", json={"kind": "http_bearer"}
        ).status_code
        == 422
    )
    assert (
        c.put(
            f"/api/agents/{agent['id']}/credentials/bearer", json={"kind": "api_key", "value": "x"}
        ).status_code
        == 422
    )


@pytest.fixture(scope="module")
def idp():
    from a2a_workbench.fixtures.idp import IdpServer

    with IdpServer() as server:
        yield server


@pytest.fixture(scope="module")
def oauth_zoo(idp):
    with ZooServer(auth="oauth", idp=idp.idp, grpc=False) as zoo:
        yield zoo


def test_oauth_client_credentials_sign_in_endpoint(c, oauth_zoo):
    from a2a_workbench.fixtures.idp import IDP_CLIENT

    agent = c.post("/api/agents", json={"url": oauth_zoo.base_url}).json()
    r = c.post(
        f"/api/agents/{agent['id']}/oauth/oauth/sign-in",
        json={
            "flow": "client_credentials",
            "client_id": IDP_CLIENT["id"],
            "client_secret": IDP_CLIENT["secret"],
            "scopes": ["a2a:invoke"],
        },
    )
    assert r.status_code == 200, r.text
    assert IDP_CLIENT["secret"] not in r.text
    sec = c.get(f"/api/agents/{agent['id']}/security").json()
    assert sec["status"] == "signed_in" and sec["active"] == ["oauth"]
    oauth = next(s for s in sec["schemes"] if s["name"] == "oauth")
    assert oauth["credential"]["preview"].startswith("signed in")
    assert IDP_CLIENT["secret"] not in c.get(f"/api/agents/{agent['id']}/security").text


def test_oauth_sign_in_with_wrong_secret_is_422_auth(c, oauth_zoo):
    agent = c.post("/api/agents", json={"url": oauth_zoo.base_url}).json()
    r = c.post(
        f"/api/agents/{agent['id']}/oauth/oauth/sign-in",
        json={
            "flow": "client_credentials",
            "client_id": "workbench-client",
            "client_secret": "nope",
        },
    )
    assert r.status_code == 422 and r.json()["error"]["reason"] == "invalid_client"
