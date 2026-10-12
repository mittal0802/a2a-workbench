import json

from typer.testing import CliRunner

from a2a_workbench.cli.main import app

runner = CliRunner()


def test_db_current_then_upgrade():
    before = runner.invoke(app, ["db", "current", "--json"])
    assert before.exit_code == 0, before.output
    out = json.loads(before.stdout)
    assert out["revision"] is None and out["head"] == "0001"
    assert out["database"].startswith("sqlite+aiosqlite:///")

    up = runner.invoke(app, ["db", "upgrade"])
    assert up.exit_code == 0, up.output
    assert "0001" in up.stdout

    after = json.loads(runner.invoke(app, ["db", "current", "--json"]).stdout)
    assert after["revision"] == "0001"


def test_db_current_masks_the_password(monkeypatch):
    monkeypatch.setenv("A2AW_DATABASE_URL", "postgresql+asyncpg://u:s3cret@127.0.0.1:1/x")
    r = runner.invoke(app, ["db", "current", "--json"])
    assert r.exit_code == 6
    err = json.loads(r.stdout)["error"]
    assert err["category"] == "workbench" and "u:***@127.0.0.1:1/x" in err["message"]
    assert "s3cret" not in r.output
