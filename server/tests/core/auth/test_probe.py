import pytest

from a2a_workbench.core.a2a_json import card_from_json
from a2a_workbench.fixtures.auth import ZOO_SECRETS
from a2a_workbench.fixtures.runner import ZooServer


class LeakyZoo(ZooServer):
    """A zoo that declares bearer auth on its card but enforces nothing."""

    def __init__(self):
        super().__init__(auth="none", grpc=False)


@pytest.fixture
async def bearer_agent(wb):
    async with ZooServer(auth="bearer", grpc=False) as zoo:
        yield await wb.agents.add(zoo.base_url)


async def test_probe_on_enforcing_agent(wb, bearer_agent):
    await wb.credentials.put(
        bearer_agent.id, "bearer", "http_bearer", {"token": ZOO_SECRETS["token"]}
    )
    results = {
        r.check: r for r in await wb.auth.probe(bearer_agent.id, card_from_json(bearer_agent.card))
    }
    assert results["rejects_anonymous"].outcome == "pass"
    assert results["rejects_wrong_credentials"].outcome == "pass"
    assert results["accepts_your_credentials"].outcome == "pass"


async def test_probe_without_saved_credentials_skips_last_check(wb, bearer_agent):
    results = {
        r.check: r for r in await wb.auth.probe(bearer_agent.id, card_from_json(bearer_agent.card))
    }
    assert results["accepts_your_credentials"].outcome == "skipped"


async def test_probe_flags_agent_that_does_not_enforce_its_card(wb):
    from a2a.types import HTTPAuthSecurityScheme, SecurityRequirement, SecurityScheme, StringList

    async with ZooServer(auth="none", grpc=False) as zoo:
        agent = await wb.agents.add(zoo.base_url)
        card = card_from_json(agent.card)
        card.security_schemes["bearer"].CopyFrom(
            SecurityScheme(http_auth_security_scheme=HTTPAuthSecurityScheme(scheme="Bearer"))
        )
        card.security_requirements.append(SecurityRequirement(schemes={"bearer": StringList()}))
        results = {r.check: r for r in await wb.auth.probe(agent.id, card)}
    assert results["rejects_anonymous"].outcome == "fail"
    assert "accepted a call without credentials" in results["rejects_anonymous"].detail


async def test_probe_on_open_agent_is_not_applicable(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)
    results = await wb.auth.probe(agent.id, card_from_json(agent.card))
    assert [r.outcome for r in results] == ["not_applicable"]
