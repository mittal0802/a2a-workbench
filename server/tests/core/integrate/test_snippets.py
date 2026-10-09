import ast
import os
import subprocess
import sys

import pytest

from a2a_workbench.core.a2a_json import card_from_json
from a2a_workbench.core.integrate.templates import TARGETS, render
from a2a_workbench.fixtures.auth import ZOO_SECRETS
from a2a_workbench.fixtures.runner import ZooServer


def _run(code, tmp_path, env):
    path = tmp_path / "call_agent.py"
    path.write_text(code)
    return subprocess.run(
        [sys.executable, str(path)],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, **env},
    )


async def test_sdk_snippet_runs_against_the_zoo(wb, zoo, tmp_path):
    agent = await wb.agents.add(zoo.base_url)
    snippet = render(
        card_from_json(agent.card), f"{zoo.base_url}/.well-known/agent-card.json", "sdk"
    )
    out = _run(snippet.code, tmp_path, {"A2A_MESSAGE": "ask", "A2A_REPLY": "B"})
    assert out.returncode == 0, out.stderr
    assert "Which option should I pick: A or B?" in out.stdout and "You chose: B" in out.stdout


async def test_sdk_snippet_follow_up_references_the_finished_task(wb, zoo, tmp_path):
    agent = await wb.agents.add(zoo.base_url)
    snippet = render(
        card_from_json(agent.card), f"{zoo.base_url}/.well-known/agent-card.json", "sdk"
    )
    out = _run(snippet.code, tmp_path, {"A2A_MESSAGE": "echo first", "A2A_FOLLOW_UP": "inspect"})
    assert out.returncode == 0, out.stderr
    assert "referenceTaskIds" in out.stdout


async def test_sdk_snippet_authenticates_with_bearer_from_env(wb, tmp_path):
    async with ZooServer(auth="bearer", grpc=False) as zoo:
        agent = await wb.agents.add(zoo.base_url)
        snippet = render(
            card_from_json(agent.card), f"{zoo.base_url}/.well-known/agent-card.json", "sdk"
        )
        assert snippet.env == {"A2A_BEARER_TOKEN": "Bearer token for scheme 'bearer' (HTTP Bearer)"}
        denied = _run(
            snippet.code, tmp_path, {"A2A_MESSAGE": "echo hi", "A2A_BEARER_TOKEN": "wrong"}
        )
        assert denied.returncode != 0
        ok = _run(
            snippet.code,
            tmp_path,
            {"A2A_MESSAGE": "echo hi", "A2A_BEARER_TOKEN": ZOO_SECRETS["token"]},
        )
        assert ok.returncode == 0, ok.stderr
        assert "echo hi" in ok.stdout


@pytest.mark.parametrize(
    "mode", ["none", "apikey-header", "apikey-query", "apikey-cookie", "basic", "bearer", "and"]
)
@pytest.mark.parametrize("target", TARGETS)
async def test_every_snippet_parses_and_has_no_secrets(wb, mode, target):
    async with ZooServer(auth=mode, grpc=False) as zoo:
        agent = await wb.agents.add(zoo.base_url)
        snippet = render(
            card_from_json(agent.card), f"{zoo.base_url}/.well-known/agent-card.json", target
        )
    ast.parse(snippet.code)
    for key in ("api_key", "password", "token"):
        assert ZOO_SECRETS[key] not in snippet.code
    assert snippet.install and snippet.language == "python"
    assert "A2A §" in snippet.code


async def test_oauth_client_credentials_snippet_uses_the_card_token_url(wb):
    from a2a_workbench.fixtures.idp import IdpServer

    with IdpServer() as idp:
        async with ZooServer(auth="oauth", idp=idp.idp, grpc=False) as zoo:
            agent = await wb.agents.add(zoo.base_url)
            snippet = render(
                card_from_json(agent.card), f"{zoo.base_url}/.well-known/agent-card.json", "sdk"
            )
    assert f"{idp.idp.issuer}/token" in snippet.code
    assert "client_credentials" in snippet.code and "A2A_OAUTH_CLIENT_SECRET" in snippet.env
    ast.parse(snippet.code)
