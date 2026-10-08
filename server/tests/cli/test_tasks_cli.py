import json

from typer.testing import CliRunner

from a2a_workbench.cli.main import app

runner = CliRunner()


def _task(zoo):
    lines = runner.invoke(app, ["send", zoo.base_url, "echo t", "--no-stream", "--json"]).stdout
    last = json.loads(lines.splitlines()[-1])
    return last["task_id"], last["context_id"]


def test_tasks_get_list_cancel(zoo):
    task_id, ctx = _task(zoo)
    got = json.loads(runner.invoke(app, ["tasks", "get", "Zoo agent", task_id, "--json"]).stdout)
    assert got["state"] == "completed"
    listed = json.loads(
        runner.invoke(app, ["tasks", "list", "Zoo agent", "--context-id", ctx, "--json"]).stdout
    )
    assert [t["id"] for t in listed["tasks"]] == [task_id]
    r = runner.invoke(app, ["tasks", "cancel", "Zoo agent", task_id, "--json"])
    assert r.exit_code == 5 and json.loads(r.stdout)["error"]["reason"] == "TASK_NOT_CANCELABLE"


def test_tasks_list_all_pages(zoo):
    for i in range(3):
        runner.invoke(app, ["send", zoo.base_url, f"echo {i}", "--no-stream"])
    r = runner.invoke(app, ["tasks", "list", "Zoo agent", "--page-size", "1", "--all", "--json"])
    assert r.exit_code == 0 and len(json.loads(r.stdout)["tasks"]) >= 3


def test_tasks_subscribe_ndjson(zoo):
    out = runner.invoke(
        app, ["send", zoo.base_url, "long", "--no-stream", "--return-immediately", "--json"]
    ).stdout
    task_id = json.loads(out.splitlines()[-1])["task_id"]
    r = runner.invoke(app, ["tasks", "subscribe", "Zoo agent", task_id, "--json"])
    events = [json.loads(line) for line in r.stdout.splitlines()]
    assert events[0]["kind"] == "task" and events[-1]["state"] == "completed"


def test_tasks_human_list(zoo):
    _task(zoo)
    r = runner.invoke(app, ["tasks", "list", "Zoo agent"])
    assert "completed" in r.stdout
