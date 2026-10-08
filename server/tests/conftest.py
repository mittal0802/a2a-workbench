import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("A2AW_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("A2AW_DATABASE_URL", raising=False)


@pytest.fixture(scope="session")
def zoo():
    from a2a_workbench.fixtures.runner import ZooServer

    with ZooServer() as server:
        yield server


@pytest.fixture(scope="session")
def unsigned_zoo():
    from a2a_workbench.fixtures.runner import ZooServer

    with ZooServer(signed=False) as server:
        yield server


@pytest.fixture(scope="session")
def custom_path_zoo():
    from a2a_workbench.fixtures.runner import ZooServer

    with ZooServer(card_path="/agents/zoo/card.json") as server:
        yield server
