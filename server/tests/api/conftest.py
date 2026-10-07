import pytest
from fastapi.testclient import TestClient

from a2a_workbench.api.app import create_app


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c
