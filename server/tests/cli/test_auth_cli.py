import json
import threading
import time

import httpx
import pytest
from typer.testing import CliRunner

from a2a_workbench.cli.main import app
from a2a_workbench.fixtures.auth import ZOO_SECRETS
from a2a_workbench.fixtures.idp import IDP_CLIENT, IdpServer
from a2a_workbench.fixtures.runner import ZooServer

runner = CliRunner()


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


def test_auth_set_status_then_send(bearer_zoo):
    assert runner.invoke(app, ["agents", "add", bearer_zoo.base_url]).exit_code == 0
    status = json.loads(
        runner.invoke(app, ["auth", "status", bearer_zoo.base_url, "--json"]).stdout
    )
    assert status["status"] == "sign_in_needed"
    assert runner.invoke(app, ["send", bearer_zoo.base_url, "echo x", "--no-stream"]).exit_code == 4
    r = runner.invoke(
        app, ["auth", "set", bearer_zoo.base_url, "bearer", "--token", ZOO_SECRETS["token"]]
    )
    assert r.exit_code == 0 and ZOO_SECRETS["token"] not in r.stdout
    assert runner.invoke(app, ["send", bearer_zoo.base_url, "echo x", "--no-stream"]).exit_code == 0
    assert runner.invoke(app, ["auth", "logout", bearer_zoo.base_url, "bearer"]).exit_code == 0
    assert (
        json.loads(runner.invoke(app, ["auth", "status", bearer_zoo.base_url, "--json"]).stdout)[
            "status"
        ]
        == "sign_in_needed"
    )


def test_auth_login_client_credentials(oauth_zoo):
    r = runner.invoke(
        app,
        [
            "auth",
            "login",
            oauth_zoo.base_url,
            "oauth",
            "--client-id",
            IDP_CLIENT["id"],
            "--client-secret",
            IDP_CLIENT["secret"],
            "--scope",
            "a2a:invoke",
            "--json",
        ],
    )
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["kind"] == "oauth2"
    assert runner.invoke(app, ["send", oauth_zoo.base_url, "echo y", "--no-stream"]).exit_code == 0


def test_auth_login_bad_secret_exit_4(oauth_zoo):
    r = runner.invoke(
        app,
        [
            "auth",
            "login",
            oauth_zoo.base_url,
            "oauth",
            "--client-id",
            IDP_CLIENT["id"],
            "--client-secret",
            "nope",
            "--json",
        ],
    )
    assert r.exit_code == 4 and json.loads(r.stdout)["error"]["reason"] == "invalid_client"


def test_auth_login_device_code(oauth_zoo, idp):
    def approve_when_requested():
        for _ in range(200):
            time.sleep(0.05)
            for grant in list(idp.idp.devices.values()):
                grant["approved"] = True
                return

    threading.Thread(target=approve_when_requested, daemon=True).start()
    r = runner.invoke(
        app,
        [
            "auth",
            "login",
            oauth_zoo.base_url,
            "oauthDevice",
            "--client-id",
            IDP_CLIENT["id"],
            "--scope",
            "a2a:invoke",
        ],
    )
    assert r.exit_code == 0, r.output
    assert "Signed in" in r.output and "enter code" in r.output


def test_auth_login_browser_flow_with_local_callback(oauth_zoo):
    from urllib.parse import parse_qs, urlparse

    def act_as_browser():
        for _ in range(200):
            time.sleep(0.05)
            path = "/tmp/a2aw-test-authorize-url"
            try:
                url = open(path).read().strip()
            except FileNotFoundError:
                continue
            data = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
            location = httpx.post(url.split("?")[0], data=data, follow_redirects=False).headers[
                "location"
            ]
            httpx.get(location)
            return

    import os

    if os.path.exists("/tmp/a2aw-test-authorize-url"):
        os.remove("/tmp/a2aw-test-authorize-url")
    threading.Thread(target=act_as_browser, daemon=True).start()
    r = runner.invoke(
        app,
        [
            "auth",
            "login",
            oauth_zoo.base_url,
            "oauthCode",
            "--client-id",
            IDP_CLIENT["id"],
            "--scope",
            "a2a:invoke",
            "--no-browser",
            "--url-file",
            "/tmp/a2aw-test-authorize-url",
        ],
    )
    assert r.exit_code == 0, r.output
    assert "Signed in" in r.output


def test_auth_probe_json(bearer_zoo):
    runner.invoke(app, ["agents", "add", bearer_zoo.base_url])
    r = runner.invoke(app, ["auth", "probe", bearer_zoo.base_url, "--json"])
    assert r.exit_code == 0
    assert json.loads(r.stdout)[0]["check"] == "rejects_anonymous"


def test_send_with_skill_applies_the_skill_requirements(oauth_zoo, idp):
    token = idp.idp.issue(IDP_CLIENT["id"], "a2a:invoke", subject="zoo")["access_token"]
    assert (
        runner.invoke(
            app, ["auth", "set", oauth_zoo.base_url, "oauthCode", "--access-token", token]
        ).exit_code
        == 0
    )
    plain = runner.invoke(app, ["send", oauth_zoo.base_url, "hold AI175", "--no-stream", "--json"])
    assert plain.exit_code == 0, plain.output
    assert '"auth_required"' in plain.stdout
    skill = runner.invoke(
        app, ["send", oauth_zoo.base_url, "hold AI175", "--no-stream", "--skill", "hold", "--json"]
    )
    assert skill.exit_code == 4, skill.output


def test_secrets_can_come_from_environment_or_stdin(bearer_zoo, oauth_zoo):
    r = runner.invoke(
        app,
        ["auth", "set", bearer_zoo.base_url, "bearer", "--json"],
        env={"A2AW_TOKEN": ZOO_SECRETS["token"]},
    )
    assert r.exit_code == 0, r.output
    assert runner.invoke(app, ["send", bearer_zoo.base_url, "echo hi", "--json"]).exit_code == 0
    r = runner.invoke(
        app,
        [
            "auth",
            "login",
            oauth_zoo.base_url,
            "oauth",
            "--client-id",
            IDP_CLIENT["id"],
            "--client-secret",
            "-",
            "--scope",
            "a2a:invoke",
            "--json",
        ],
        input=IDP_CLIENT["secret"] + "\n",
    )
    assert r.exit_code == 0, r.output
    assert IDP_CLIENT["secret"] not in r.stdout


def test_cli_integrate_prints_code_and_json(zoo):
    r = runner.invoke(app, ["integrate", zoo.base_url, "--target", "langgraph"])
    assert r.exit_code == 0, r.output
    assert "create_react_agent" in r.stdout and "call_agent" in r.stdout
    r = runner.invoke(app, ["integrate", zoo.base_url, "--json"])
    body = json.loads(r.stdout)
    assert set(body["snippets"]) == {"sdk", "adk", "langgraph", "openai", "claude"}
    assert runner.invoke(app, ["integrate", zoo.base_url, "--target", "nope"]).exit_code == 2
