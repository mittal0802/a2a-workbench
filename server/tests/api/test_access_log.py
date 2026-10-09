import logging

from typer.testing import CliRunner

from a2a_workbench.api.logs import RedactOAuthQuery, log_config
from a2a_workbench.cli.main import app


def _record(path):
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "GET", path, "1.1", 200),
        None,
    )


def test_oauth_query_strings_are_masked_in_access_logs():
    record = _record("/oauth/callback?code=SECRET-CODE&state=abc")
    assert RedactOAuthQuery().filter(record)
    assert (
        "SECRET-CODE" not in record.getMessage() and "/oauth/callback?••••" in record.getMessage()
    )
    other = _record("/api/agents?x=1")
    RedactOAuthQuery().filter(other)
    assert "/api/agents?x=1" in other.getMessage()


def test_serve_installs_the_filter(monkeypatch):
    seen = {}
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: seen.update(k))
    assert CliRunner().invoke(app, ["serve", "--port", "8599"]).exit_code == 0
    access = seen["log_config"]["handlers"]["access"]
    assert "redact_oauth" in access["filters"]
    assert seen["log_config"] == log_config()


def test_serve_binds_the_settings_to_its_host_and_port(monkeypatch):
    seen = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **k: seen.update(app=app, **k))
    assert CliRunner().invoke(app, ["serve", "--port", "8599"]).exit_code == 0
    wb = seen["app"].state.workbench
    assert seen["port"] == 8599 and wb.settings.port == 8599
    assert wb.public_base_url() == "http://127.0.0.1:8599"
