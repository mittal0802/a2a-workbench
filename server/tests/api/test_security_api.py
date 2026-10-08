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


def test_overview_lists_required_scopes(c, oauth_zoo):
    agent = c.post("/api/agents", json={"url": oauth_zoo.base_url}).json()
    sec = c.get(f"/api/agents/{agent['id']}/security").json()
    assert sec["required_scopes"]["oauth"] == ["a2a:invoke"]


def _approve(authorize_url):
    from urllib.parse import parse_qs, urlparse

    import httpx

    data = {k: v[0] for k, v in parse_qs(urlparse(authorize_url).query).items()}
    r = httpx.post(authorize_url.split("?")[0], data=data, follow_redirects=False)
    return r.headers["location"]


def test_browser_sign_in_round_trip_through_callback(c, oauth_zoo):
    from urllib.parse import urlparse

    from a2a_workbench.fixtures.idp import IDP_CLIENT

    agent = c.post("/api/agents", json={"url": oauth_zoo.base_url}).json()
    start = c.post(
        f"/api/agents/{agent['id']}/oauth/oauthCode/start",
        json={"client_id": IDP_CLIENT["id"], "scopes": ["a2a:invoke"]},
    ).json()
    assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A8484%2Foauth%2Fcallback" in start["authorize_url"]
    assert start["redirect_uri"] == "http://127.0.0.1:8484/oauth/callback"
    location = _approve(start["authorize_url"])
    page = c.get(urlparse(location).path + "?" + urlparse(location).query)
    assert page.status_code == 200 and "Signed in" in page.text
    sec = c.get(f"/api/agents/{agent['id']}/security").json()
    assert sec["status"] == "signed_in" and "oauthCode" in sec["active"]


def test_callback_with_provider_error_shows_it(c):
    page = c.get("/oauth/callback?error=access_denied&error_description=User+said+no&state=nope")
    assert page.status_code == 400 and "User said no" in page.text


def test_implicit_callback_page_posts_the_fragment(c, oauth_zoo):
    from urllib.parse import parse_qs, urlparse

    from a2a_workbench.fixtures.idp import IDP_CLIENT

    agent = c.post("/api/agents", json={"url": oauth_zoo.base_url}).json()
    start = c.post(
        f"/api/agents/{agent['id']}/oauth/oauthImplicit/start",
        json={"client_id": IDP_CLIENT["id"], "scopes": ["a2a:invoke"]},
    ).json()
    fragment = parse_qs(urlparse(_approve(start["authorize_url"])).fragment)
    assert "location.hash" in c.get("/oauth/callback").text
    r = c.post("/oauth/implicit", json={k: v[0] for k, v in fragment.items()})
    assert r.status_code == 200
    assert c.get(f"/api/agents/{agent['id']}/security").json()["status"] == "signed_in"


def test_device_sign_in_endpoints(c, oauth_zoo):
    import httpx

    from a2a_workbench.fixtures.idp import IDP_CLIENT

    agent = c.post("/api/agents", json={"url": oauth_zoo.base_url}).json()
    d = c.post(
        f"/api/agents/{agent['id']}/oauth/oauthDevice/device",
        json={"client_id": IDP_CLIENT["id"], "scopes": ["a2a:invoke"]},
    ).json()
    assert c.get(f"/api/oauth/device/{d['flow_id']}").json()["status"] == "pending"
    httpx.post(d["verification_uri"], data={"user_code": d["user_code"]})
    assert c.get(f"/api/oauth/device/{d['flow_id']}").json()["status"] == "signed_in"
