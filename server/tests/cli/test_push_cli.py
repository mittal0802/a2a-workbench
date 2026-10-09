import json

from typer.testing import CliRunner

from a2a_workbench.cli.main import app

runner = CliRunner()


def _task(zoo):
    r = runner.invoke(
        app, ["send", zoo.base_url, "slow 20", "--no-stream", "--return-immediately", "--json"]
    )
    return next(
        json.loads(line)["task_id"]
        for line in r.stdout.splitlines()
        if json.loads(line).get("task_id")
    )


def test_cli_push_create_list_get_delete_and_deliveries(zoo):
    task = _task(zoo)
    r = runner.invoke(app, ["push", "create", zoo.base_url, task, "--json"])
    assert r.exit_code == 0, r.output
    created = json.loads(r.stdout)
    cid = created["config"]["id"]
    listed = json.loads(runner.invoke(app, ["push", "list", zoo.base_url, task, "--json"]).stdout)
    assert [x["id"] for x in listed["configs"]] == [cid]
    assert created["hook"]["credentials"] not in json.dumps(listed)
    got = json.loads(runner.invoke(app, ["push", "get", zoo.base_url, task, cid, "--json"]).stdout)
    assert got["id"] == cid
    assert runner.invoke(app, ["push", "delete", zoo.base_url, task, cid]).exit_code == 0
    assert (
        json.loads(runner.invoke(app, ["push", "deliveries", zoo.base_url, "--json"]).stdout) == []
    )
    r = runner.invoke(
        app,
        [
            "push",
            "create",
            zoo.base_url,
            task,
            "--url",
            "https://hooks.example/a",
            "--token",
            "-",
            "--json",
        ],
        input="tok-from-stdin\n",
    )
    assert r.exit_code == 0 and json.loads(r.stdout)["config"]["token"] == "••••"


def test_cli_send_with_push(zoo):
    r = runner.invoke(
        app, ["send", zoo.base_url, "echo with push", "--push", "--no-stream", "--json"]
    )
    assert r.exit_code == 0, r.output
    first = json.loads(r.stdout.splitlines()[0])
    assert first["data"]["options"]["push"] is True
