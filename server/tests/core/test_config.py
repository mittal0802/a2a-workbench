from pathlib import Path

from a2a_workbench.core.config import Settings


def test_defaults_use_home_state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("A2AW_HOME", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = Settings()
    assert s.home == tmp_path
    assert s.host == "127.0.0.1"
    assert s.port == 8484
    assert s.mode == "local"
    assert s.resolved_database_url == f"sqlite+aiosqlite:///{tmp_path / 'workbench.db'}"


def test_database_url_accepts_unprefixed_env(tmp_path, monkeypatch):
    monkeypatch.setenv("A2AW_HOME", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    assert Settings().resolved_database_url == "postgresql+asyncpg://u:p@h/db"


def test_default_home_is_dot_dir(monkeypatch):
    monkeypatch.delenv("A2AW_HOME", raising=False)
    assert Settings().home == Path.home() / ".a2a-workbench"
