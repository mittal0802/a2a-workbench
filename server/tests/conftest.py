import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("A2AW_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("A2AW_DATABASE_URL", raising=False)
