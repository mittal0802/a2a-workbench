import pytest
from fastapi.testclient import TestClient

from a2a_workbench.api.app import create_app


@pytest.fixture
def client():
    with TestClient(create_app(), base_url="http://127.0.0.1:8484") as c:
        yield c
