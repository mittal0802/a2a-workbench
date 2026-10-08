import pytest

from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.conversations.parts import TextPartInput
from a2a_workbench.fixtures.certs import make_test_pki
from a2a_workbench.fixtures.mtls import MtlsZooServer


@pytest.fixture(scope="module")
def pki(tmp_path_factory):
    return make_test_pki(tmp_path_factory.mktemp("pki"))


async def _send(wb, conv_id, text):
    return [
        e
        async for e in wb.conversations.send(
            conv_id, [TextPartInput(text=text)], SendOptions(stream=False)
        )
    ]


async def test_mtls_agent_needs_a_client_certificate(wb, pki):
    async with MtlsZooServer(pki) as zoo:
        agent = await wb.agents.add(zoo.card_url)
        assert agent.selected_interface_url.startswith("https://")
        conv = await wb.conversations.create(agent.id)
        without = await _send(wb, conv.id, "echo no cert")
        assert without[-1].kind == "error" and without[-1].data["category"] == "transport"
        await wb.auth.set_credential(
            agent.id,
            __import__("a2a_workbench.core.a2a_json", fromlist=["x"]).card_from_json(agent.card),
            "mtls",
            "mtls",
            {"cert_pem": pki.client_cert, "key_pem": pki.client_key, "ca_pem": pki.ca_cert},
        )
        with_cert = await _send(wb, conv.id, "echo with cert")
        assert with_cert[-1].data.get("state") == "completed"
