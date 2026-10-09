import pytest

from a2a_workbench.core.assistant.keys import ENV_VARS


@pytest.fixture(autouse=True)
def _no_provider_keys_from_env(monkeypatch):
    for names in ENV_VARS.values():
        for name in names:
            monkeypatch.delenv(name, raising=False)
