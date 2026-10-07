import httpx

from a2a_workbench.fixtures.runner import ZooServer


def test_zoo_serves_signed_card_and_jwks():
    with ZooServer() as zoo:
        card = httpx.get(f"{zoo.base_url}/.well-known/agent-card.json").json()
        jwks = httpx.get(f"{zoo.base_url}/.well-known/jwks.json").json()
    assert card["name"] == "Zoo agent"
    bindings = {i["protocolBinding"] for i in card["supportedInterfaces"]}
    assert bindings == {"JSONRPC", "HTTP+JSON"}
    assert card["capabilities"]["streaming"] is True
    assert card["signatures"]
    assert jwks["keys"][0]["kid"] == "zoo-1"


def test_unsigned_zoo_has_no_signatures():
    with ZooServer(signed=False) as zoo:
        card = httpx.get(f"{zoo.base_url}/.well-known/agent-card.json").json()
    assert "signatures" not in card
