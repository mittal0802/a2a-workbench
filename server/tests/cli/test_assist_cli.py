import json

import pytest
from typer.testing import CliRunner

from a2a_workbench.cli.main import app
from a2a_workbench.core.assistant.keys import ENV_VARS
from a2a_workbench.fixtures.llm import FakeOpenAIServer

runner = CliRunner()


@pytest.fixture(autouse=True)
def _no_env_keys(monkeypatch):
    for names in ENV_VARS.values():
        for name in names:
            monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="module")
def llm():
    with FakeOpenAIServer() as server:
        yield server


def _lines(out):
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def test_cli_providers_set_list_remove(llm):
    r = runner.invoke(
        app,
        ["providers", "set", "openai", "--base-url", llm.base_url, "--json"],
        env={"A2AW_LLM_API_KEY": "sk-cli-secret-4321"},
    )
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["preview"] == "••••4321" and "sk-cli-secret" not in r.stdout
    listed = {
        p["provider"]: p
        for p in json.loads(runner.invoke(app, ["providers", "list", "--json"]).stdout)
    }
    assert listed["openai"]["configured"] and listed["openai"]["base_url"] == llm.base_url
    assert runner.invoke(app, ["providers", "remove", "openai"]).exit_code == 0
    assert not json.loads(runner.invoke(app, ["providers", "list", "--json"]).stdout)[1][
        "configured"
    ]


def test_cli_assist_ndjson_and_exit_codes(llm, zoo):
    runner.invoke(
        app,
        ["providers", "set", "openai", "--base-url", llm.base_url],
        env={"A2AW_LLM_API_KEY": "sk-cli-secret-4321"},
    )
    r = runner.invoke(
        app,
        [
            "assist",
            "ask",
            "--agents",
            zoo.base_url,
            "--provider",
            "openai",
            "--model",
            "scripted",
            "--json",
        ],
    )
    assert r.exit_code == 0, r.output
    lines = _lines(r.stdout)
    assert lines[-1]["session"]["status"] == "idle"
    steps = [x for x in lines if "kind" in x]
    assert steps[-1]["kind"] == "done" and steps[-1]["data"]["text"] == "Done: You chose: B"
    assert "sk-cli-secret" not in r.output

    r = runner.invoke(
        app,
        [
            "assist",
            "ask",
            "--agents",
            zoo.base_url,
            "--provider",
            "openai",
            "--model",
            "scripted",
            "--response-mode",
            "pass-through",
            "--json",
        ],
    )
    session = _lines(r.stdout)[-1]["session"]
    assert r.exit_code == 0 and session["status"] == "awaiting_user"
    r = runner.invoke(app, ["assist", "A", "--session", session["id"], "--json"])
    assert r.exit_code == 0 and _lines(r.stdout)[-2]["data"]["text"] == "Done: You chose: A"

    r = runner.invoke(
        app,
        [
            "assist",
            "loop forever",
            "--agents",
            zoo.base_url,
            "--provider",
            "openai",
            "--model",
            "scripted",
            "--max-steps",
            "2",
            "--json",
        ],
    )
    assert r.exit_code == 1 and _lines(r.stdout)[-2]["data"]["limit"] == "max_steps"


def test_cli_assist_without_key_is_auth_exit(zoo):
    r = runner.invoke(
        app, ["assist", "hi", "--agents", zoo.base_url, "--provider", "gemini", "--model", "g"]
    )
    assert r.exit_code == 4 and "No API key for gemini" in r.output


def test_cli_assist_human_output(llm, zoo):
    runner.invoke(
        app,
        ["providers", "set", "openai", "--base-url", llm.base_url],
        env={"A2AW_LLM_API_KEY": "sk-cli-secret-4321"},
    )
    r = runner.invoke(
        app,
        [
            "assist",
            "echo hi",
            "--agents",
            zoo.base_url,
            "--provider",
            "openai",
            "--model",
            "scripted",
        ],
    )
    assert r.exit_code == 0, r.output
    assert "Zoo agent" in r.output and "Done: echo hi" in r.output
