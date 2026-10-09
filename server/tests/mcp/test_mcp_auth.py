import pytest

from a2a_workbench.fixtures.idp import IDP_CLIENT, IdpServer
from a2a_workbench.fixtures.runner import ZooServer
from tests.mcp.test_mcp_server import call, connected


@pytest.fixture(scope="module")
def bearer_zoo():
    with ZooServer(auth="bearer", grpc=False) as zoo:
        yield zoo


@pytest.fixture(scope="module")
def idp():
    with IdpServer() as server:
        yield server


@pytest.fixture(scope="module")
def oauth_zoo(idp):
    with ZooServer(auth="oauth", idp=idp.idp, grpc=False) as zoo:
        yield zoo


async def test_auth_tools_listed():
    async with connected() as c:
        names = {t.name for t in (await c.list_tools()).tools}
    assert {
        "auth_status",
        "set_credential",
        "sign_in",
        "poll_sign_in",
        "sign_out",
        "auth_probe",
    } <= names


async def test_set_credential_then_send(bearer_zoo):
    async with connected() as c:
        status = await call(c, "auth_status", {"agent": bearer_zoo.base_url})
        assert status["status"] == "sign_in_needed"
        failed = await call(c, "send_message", {"agent": bearer_zoo.base_url, "text": "hi"})
        assert failed["error"]["category"] == "auth"
        saved = await call(
            c,
            "set_credential",
            {"agent": bearer_zoo.base_url, "scheme": "bearer", "token": "zoo-token-5678"},
        )
        assert "zoo-token-5678" not in str(saved) and saved["readable"] is True
        ok = await call(c, "send_message", {"agent": bearer_zoo.base_url, "text": "hi"})
        assert ok["final_state"] == "completed"
        probe = await call(c, "auth_probe", {"agent": bearer_zoo.base_url})
        assert {r["outcome"] for r in probe["results"]} <= {"pass", "skip"}
        await call(c, "sign_out", {"agent": bearer_zoo.base_url, "scheme": "bearer"})
        assert (await call(c, "auth_status", {"agent": bearer_zoo.base_url}))[
            "status"
        ] == "sign_in_needed"


async def test_sign_in_client_credentials_and_bad_secret(oauth_zoo):
    async with connected() as c:
        bad = await call(
            c,
            "sign_in",
            {
                "agent": oauth_zoo.base_url,
                "scheme": "oauth",
                "client_id": IDP_CLIENT["id"],
                "client_secret": "nope",
                "scopes": ["a2a:invoke"],
            },
        )
        assert bad["error"]["reason"] == "invalid_client"
        ok = await call(
            c,
            "sign_in",
            {
                "agent": oauth_zoo.base_url,
                "scheme": "oauth",
                "client_id": IDP_CLIENT["id"],
                "client_secret": IDP_CLIENT["secret"],
                "scopes": ["a2a:invoke"],
            },
        )
        assert ok["scheme_name"] == "oauth" and ok["readable"] is True


async def test_device_sign_in_returns_code_then_polls(oauth_zoo, idp):
    async with connected() as c:
        started = await call(
            c,
            "sign_in",
            {
                "agent": oauth_zoo.base_url,
                "scheme": "oauthDevice",
                "client_id": IDP_CLIENT["id"],
                "scopes": ["a2a:invoke"],
            },
        )
        assert started["user_code"] and started["verification_uri"] and started["flow_id"]
        assert (await call(c, "poll_sign_in", {"flow_id": started["flow_id"]}))[
            "status"
        ] == "pending"
        for grant in idp.idp.devices.values():
            grant["approved"] = True
        assert (await call(c, "poll_sign_in", {"flow_id": started["flow_id"]}))[
            "status"
        ] == "signed_in"


async def test_browser_flow_points_to_web_or_cli(oauth_zoo):
    async with connected() as c:
        out = await call(
            c,
            "sign_in",
            {"agent": oauth_zoo.base_url, "scheme": "oauthCode", "client_id": IDP_CLIENT["id"]},
        )
    assert out["error"]["category"] == "workbench"
    assert "auth login" in out["error"]["message"]
