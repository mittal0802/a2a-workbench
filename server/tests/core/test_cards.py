import pytest

from a2a_workbench.core.connection.cards import CardFetchError, fetch_card, split_card_url


class Sink:
    def __init__(self):
        self.items = []

    async def __call__(self, ex):
        self.items.append(ex)


def test_split_card_url_base_only():
    assert split_card_url("https://h.dev/") == ("https://h.dev", None)


def test_split_card_url_full_well_known():
    assert split_card_url("https://h.dev/.well-known/agent-card.json") == (
        "https://h.dev",
        "/.well-known/agent-card.json",
    )


def test_split_card_url_custom_json_path_keeps_prefix():
    assert split_card_url("https://h.dev/agents/x/card.json?v=1") == (
        "https://h.dev",
        "/agents/x/card.json?v=1",
    )


def test_split_card_url_subpath_base():
    assert split_card_url("https://h.dev/agents/x") == ("https://h.dev/agents/x", None)


def test_split_card_url_trims_whitespace():
    assert split_card_url("  http://localhost:9999  ") == ("http://localhost:9999", None)


async def test_fetch_signed_card_verifies(zoo):
    sink = Sink()
    result = await fetch_card(zoo.base_url, sink)
    assert result.card.name == "Zoo agent"
    assert result.signature_status == "verified"
    assert result.card_json["name"] == "Zoo agent"
    assert len(result.exchange_ids) == 2
    assert {e.operation for e in sink.items} == {"get_agent_card"}


async def test_fetch_card_by_full_url(zoo):
    result = await fetch_card(f"{zoo.base_url}/.well-known/agent-card.json", Sink())
    assert result.card.name == "Zoo agent"


async def test_fetch_unsigned_card(unsigned_zoo):
    result = await fetch_card(unsigned_zoo.base_url, Sink())
    assert result.signature_status == "unsigned"


async def test_tampered_card_is_invalid(zoo, monkeypatch):
    from a2a_workbench.core.connection import cards

    real = cards.A2ACardResolver.get_agent_card

    async def tampered(self, *a, **k):
        card = await real(self, *a, **k)
        card.description = "tampered"
        return card

    monkeypatch.setattr(cards.A2ACardResolver, "get_agent_card", tampered)
    result = await fetch_card(zoo.base_url, Sink())
    assert result.signature_status == "invalid"


async def test_fetch_card_unreachable_raises_card_error():
    with pytest.raises(CardFetchError):
        await fetch_card("http://127.0.0.1:1", Sink())


async def test_fetch_card_404_raises_card_error(zoo):
    with pytest.raises(CardFetchError):
        await fetch_card(f"{zoo.base_url}/nope/card.json", Sink())
