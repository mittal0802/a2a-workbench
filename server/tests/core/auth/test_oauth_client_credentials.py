import json
import time

import pytest

from a2a_workbench.core.auth.oauth import OAuthError, client_credentials, discover
from a2a_workbench.fixtures.idp import IDP_CLIENT, IdpServer


class Sink(list):
    async def __call__(self, ex):
        if ex.complete:
            self.append(ex)


@pytest.fixture(scope="module")
def idp():
    with IdpServer() as server:
        yield server


@pytest.mark.parametrize("method", ["client_secret_post", "client_secret_basic"])
async def test_client_credentials_gets_a_token(idp, method):
    sink = Sink()
    tokens = await client_credentials(
        f"{idp.base_url}/token",
        IDP_CLIENT["id"],
        IDP_CLIENT["secret"],
        ["a2a:invoke"],
        sink,
        auth_method=method,
    )
    assert tokens.access_token and tokens.token_type.lower() == "bearer"
    assert tokens.expires_at > time.time() and tokens.scopes == ["a2a:invoke"]
    recorded = json.dumps([e.to_record() for e in sink])
    assert IDP_CLIENT["secret"] not in recorded and tokens.access_token not in recorded
    assert sink[0].operation == "oauth_token"


async def test_wrong_secret_is_oauth_error(idp):
    with pytest.raises(OAuthError) as info:
        await client_credentials(f"{idp.base_url}/token", IDP_CLIENT["id"], "wrong", [], Sink())
    assert info.value.error == "invalid_client"


async def test_discovery_reads_authorization_server_metadata(idp):
    meta = await discover(f"{idp.base_url}/.well-known/oauth-authorization-server", Sink())
    assert meta["token_endpoint"] == f"{idp.base_url}/token"
    assert meta["authorization_endpoint"] == f"{idp.base_url}/authorize"
