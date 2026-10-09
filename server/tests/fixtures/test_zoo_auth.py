import base64

import httpx
import pytest

from a2a_workbench.fixtures.auth import ZOO_SECRETS
from a2a_workbench.fixtures.runner import ZooServer

BODY = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "GetTask",
    "params": {"id": "nope"},
}

GOOD = {
    "apikey-header": {"headers": {"X-API-Key": ZOO_SECRETS["api_key"]}},
    "apikey-query": {"params": {"api_key": ZOO_SECRETS["api_key"]}},
    "apikey-cookie": {"headers": {"Cookie": f"zoo_session={ZOO_SECRETS['api_key']}"}},
    "basic": {
        "headers": {
            "Authorization": "Basic "
            + base64.b64encode(
                f"{ZOO_SECRETS['username']}:{ZOO_SECRETS['password']}".encode()
            ).decode()
        }
    },
    "bearer": {"headers": {"Authorization": f"Bearer {ZOO_SECRETS['token']}"}},
    "and": {
        "headers": {
            "X-API-Key": ZOO_SECRETS["api_key"],
            "Authorization": f"Bearer {ZOO_SECRETS['token']}",
        }
    },
}


@pytest.mark.parametrize("mode", list(GOOD))
def test_auth_variants_reject_anonymous_and_accept_credentials(mode):
    with ZooServer(auth=mode, grpc=False) as zoo:
        card = httpx.get(f"{zoo.base_url}/.well-known/agent-card.json").json()
        assert card["securitySchemes"] and card["securityRequirements"]
        anon = httpx.post(f"{zoo.base_url}/a2a", json=BODY, headers={"A2A-Version": "1.0"})
        assert anon.status_code == 401 and "www-authenticate" in anon.headers
        ok = httpx.post(
            f"{zoo.base_url}/a2a",
            json=BODY,
            headers={"A2A-Version": "1.0", **GOOD[mode].get("headers", {})},
            params=GOOD[mode].get("params"),
        )
        assert ok.status_code == 200, ok.text


def test_and_variant_needs_both():
    with ZooServer(auth="and", grpc=False) as zoo:
        only_key = httpx.post(
            f"{zoo.base_url}/a2a", json=BODY, headers={"X-API-Key": ZOO_SECRETS["api_key"]}
        )
        assert only_key.status_code == 401
