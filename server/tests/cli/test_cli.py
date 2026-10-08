import json

from typer.testing import CliRunner

from a2a_workbench.cli.main import app

runner = CliRunner()


def _lines(out):
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def test_card_json(zoo):
    r = runner.invoke(app, ["card", zoo.base_url, "--json"])
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["card"]["name"] == "Zoo agent" and out["signature_status"] == "verified"


def test_card_human(zoo):
    r = runner.invoke(app, ["card", zoo.base_url])
    assert r.exit_code == 0
    assert "Zoo agent" in r.stdout and "JSONRPC" in r.stdout and "skill echo" in r.stdout


def test_card_unreachable_exit_code_3():
    r = runner.invoke(app, ["card", "http://127.0.0.1:1", "--json"])
    assert r.exit_code == 3
    assert json.loads(r.stdout)["error"]["category"] == "transport"


def test_agents_add_list_remove(zoo):
    assert runner.invoke(app, ["agents", "add", zoo.base_url, "--json"]).exit_code == 0
    listed = json.loads(runner.invoke(app, ["agents", "list", "--json"]).stdout)
    assert listed[0]["name"] == "Zoo agent"
    assert runner.invoke(app, ["agents", "add", zoo.base_url]).exit_code == 2
    assert runner.invoke(app, ["agents", "remove", "Zoo agent"]).exit_code == 0
    assert json.loads(runner.invoke(app, ["agents", "list", "--json"]).stdout) == []


def test_agents_remove_unknown_is_usage_error():
    assert runner.invoke(app, ["agents", "remove", "ghost"]).exit_code == 2


def test_send_ndjson_stream(zoo):
    r = runner.invoke(app, ["send", zoo.base_url, "stream", "--json"])
    assert r.exit_code == 0, r.output
    events = _lines(r.stdout)
    assert events[0]["kind"] == "user_message"
    assert events[-1]["data"]["state"] == "completed"


def test_send_with_options_reaches_agent(zoo):
    r = runner.invoke(
        app,
        [
            "send",
            zoo.base_url,
            "inspect",
            "--json",
            "--accept",
            "text/plain",
            "--history-length",
            "1",
            "--extension",
            "https://e/x",
            "--metadata",
            '{"a":1}',
            "--data",
            '{"n":2}',
        ],
    )
    assert r.exit_code == 0, r.output
    events = _lines(r.stdout)
    artifact = next(e for e in events if e["kind"] == "artifact")
    report = artifact["data"]["assembled"]["parts"][0]["data"]
    assert report["requestedExtensions"] == ["https://e/x"]
    assert report["message"]["parts"][1]["data"] == {"n": 2}
    assert report["configuration"]["acceptedOutputModes"] == ["text/plain"]


def test_send_file_attachment(zoo, tmp_path):
    f = tmp_path / "note.txt"
    f.write_text("hi")
    r = runner.invoke(app, ["send", zoo.base_url, "inspect", "--file", str(f), "--json"])
    sent = _lines(r.stdout)[0]["data"]["message"]["parts"][1]
    assert sent["filename"] == "note.txt" and sent["mediaType"] == "text/plain"


def test_send_human_output(zoo):
    r = runner.invoke(app, ["send", zoo.base_url, "echo hello"])
    assert r.exit_code == 0
    assert "hello" in r.stdout and "completed" in r.stdout.lower()


def test_send_to_registered_agent_by_name(zoo):
    runner.invoke(app, ["agents", "add", zoo.base_url])
    r = runner.invoke(app, ["send", "Zoo agent", "echo named", "--json"])
    assert r.exit_code == 0 and _lines(r.stdout)[-1]["data"]["state"] == "completed"


def test_send_unreachable_url_exit_code_3():
    assert runner.invoke(app, ["send", "http://127.0.0.1:1", "x", "--json"]).exit_code == 3


def test_bad_metadata_json_is_usage_error(zoo):
    assert runner.invoke(app, ["send", zoo.base_url, "x", "--metadata", "{bad"]).exit_code == 2


def test_human_output_shows_artifacts_without_last_chunk(zoo):
    r = runner.invoke(app, ["send", zoo.base_url, "echo hello"])
    assert "artifact echo: echo hello" in r.stdout


def test_human_output_shows_artifacts_of_non_streaming_task(zoo):
    r = runner.invoke(app, ["send", zoo.base_url, "data", "--no-stream"])
    line = next(ln for ln in r.stdout.splitlines() if ln.startswith("artifact data: "))
    assert json.loads(line.removeprefix("artifact data: ")) == {"ok": True, "items": [1, 2, 3]}


def test_human_output_prints_streamed_artifact_once(zoo):
    r = runner.invoke(app, ["send", zoo.base_url, "stream"])
    assert r.stdout.count("artifact streamed:") == 1
    assert "Streaming in four pieces." in r.stdout


def test_human_output_shows_status_message_of_task_snapshot(zoo):
    r = runner.invoke(app, ["send", zoo.base_url, "fail", "--no-stream"])
    assert "Something went wrong." in r.stdout


def test_card_of_registered_agent_uses_its_card_path(custom_path_zoo):
    url = f"{custom_path_zoo.base_url}/agents/zoo/card.json"
    assert runner.invoke(app, ["agents", "add", url]).exit_code == 0
    r = runner.invoke(app, ["card", "Zoo agent", "--json"])
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["card"]["name"] == "Zoo agent"


def test_card_extended_json(zoo):
    r = runner.invoke(app, ["card", zoo.base_url, "--extended", "--json"])
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert any(d["path"] == "skills[visa]" for d in out["diff"])


def test_card_extended_human(zoo):
    r = runner.invoke(app, ["card", zoo.base_url, "--extended"])
    assert "added skills[visa]" in r.stdout
