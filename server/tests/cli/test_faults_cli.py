import json

from typer.testing import CliRunner

from a2a_workbench.cli.main import app

runner = CliRunner()


def test_faults_presets_json():
    out = json.loads(runner.invoke(app, ["faults", "presets", "--json"]).stdout)
    assert [p["name"] for p in out][:2] == ["stable", "flaky_stream"] and len(out) == 6


def test_faults_presets_human():
    assert "flaky_stream" in runner.invoke(app, ["faults", "presets"]).stdout


def test_faults_validate(tmp_path):
    good = tmp_path / "g.json"
    good.write_text('{"rules": [{"kind": "delay", "params": {"ms": 5}}]}')
    assert runner.invoke(app, ["faults", "validate", str(good)]).exit_code == 0
    bad = tmp_path / "b.json"
    bad.write_text('{"rules": [{"kind": "explode"}]}')
    assert runner.invoke(app, ["faults", "validate", str(bad)]).exit_code == 2


def test_send_with_flaky_stream_ends_in_connection_lost(zoo):
    r = runner.invoke(app, ["send", zoo.base_url, "long", "--faults", "flaky_stream", "--json"])
    assert r.exit_code == 3
    assert json.loads(r.stdout.splitlines()[-1])["kind"] == "connection_lost"


def test_send_with_unknown_fault_spec_is_usage_error(zoo):
    assert runner.invoke(app, ["send", zoo.base_url, "x", "--faults", "nope"]).exit_code == 2


def test_tasks_get_with_faults(zoo):
    lines = runner.invoke(app, ["send", zoo.base_url, "echo f", "--no-stream", "--json"]).stdout
    task_id = json.loads(lines.splitlines()[-1])["task_id"]
    r = runner.invoke(app, ["tasks", "get", "Zoo agent", task_id, "--faults", "offline", "--json"])
    assert r.exit_code == 3
