import json

from typer.testing import CliRunner

from a2a_workbench.cli.main import app
from a2a_workbench.fixtures.runner import ZooServer

runner = CliRunner()


def test_check_json_report_and_exit_zero(zoo):
    r = runner.invoke(app, ["check", zoo.base_url, "--area", "A,F", "--format", "json"])
    assert r.exit_code == 0, r.output
    report = json.loads(r.stdout)
    assert report["schema"] == 1 and report["score"] == 100
    assert {x["area"] for x in report["results"]} == {"A", "F"}
    progress = [json.loads(line) for line in r.stderr.splitlines() if line.startswith("{")]
    assert progress[0]["kind"] == "started" and progress[-1]["kind"] == "finished"


def test_check_fails_with_exit_one_and_text_explains():
    with ZooServer(breaks={"get-unknown-returns"}) as zoo:
        r = runner.invoke(app, ["check", zoo.base_url, "--area", "F"])
    assert r.exit_code == 1, r.output
    assert "FAIL  F2.get_unknown" in r.stdout and "fix:" in r.stdout and "Score" in r.stdout


def test_check_fail_on_warn():
    with ZooServer(breaks={"history-ignored"}) as zoo:
        lenient = runner.invoke(app, ["check", zoo.base_url, "--area", "C", "--json"])
        strict = runner.invoke(
            app, ["check", zoo.base_url, "--area", "C", "--json", "--fail-on", "warn"]
        )
    statuses = {x["check_id"]: x["status"] for x in json.loads(lenient.stdout)["results"]}
    assert statuses["C7.history_zero"] == "warn"
    assert "fail" not in statuses.values()
    assert lenient.exit_code == 0 and strict.exit_code == 1


def test_check_html_out(zoo, tmp_path):
    out = tmp_path / "report.html"
    r = runner.invoke(
        app, ["check", zoo.base_url, "--area", "A", "--format", "html", "--out", str(out)]
    )
    assert r.exit_code == 0, r.output
    assert "<html" in out.read_text().lower()


def test_check_usage_errors(zoo):
    assert runner.invoke(app, ["check", zoo.base_url, "--area", "Z"]).exit_code == 2
    assert runner.invoke(app, ["check", zoo.base_url, "--format", "pdf"]).exit_code == 2
    assert runner.invoke(app, ["check", zoo.base_url, "--faults", "nope"]).exit_code == 2


def test_check_fails_when_nothing_could_be_checked():
    with ZooServer(auth="bearer", grpc=False) as zoo:
        r = runner.invoke(app, ["check", zoo.base_url, "--area", "F", "--json"])
    report = json.loads(r.stdout)
    assert all(x["status"] == "not_supported" for x in report["results"])
    assert r.exit_code == 1 and "Nothing could be checked" in r.stderr
