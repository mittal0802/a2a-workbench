"""Construction of A2A SDK clients for a chosen agent interface."""

from a2a.client import Client, ClientConfig, ClientFactory
from a2a.types import AgentCard, AgentInterface

from a2a_workbench.core.connection.grpc import build_grpc_channel_factory
from a2a_workbench.core.connection.http import build_http_client
from a2a_workbench.core.connection.recorder import ExchangeSink
from a2a_workbench.core.faults.profile import FaultProfile

SUPPORTED_BINDINGS = ("JSONRPC", "HTTP+JSON", "GRPC")
_BINDING_PREFERENCE = ("JSONRPC", "HTTP+JSON", "GRPC")


class InterfaceNotFoundError(LookupError):
    """Raised when the card has no interface with the requested URL."""


class UnsupportedBindingError(ValueError):
    """Raised when an interface uses a protocol binding this build cannot speak."""


def _rank(iface: AgentInterface) -> tuple[int, int]:
    binding = (
        _BINDING_PREFERENCE.index(iface.protocol_binding)
        if iface.protocol_binding in _BINDING_PREFERENCE
        else len(_BINDING_PREFERENCE)
    )
    return binding, 0 if iface.protocol_version == "1.0" else 1


def select_interface(card: AgentCard, url: str | None) -> AgentInterface:
    """Return the interface at ``url``, or the preferred one when ``url`` is None.

    Preference: JSON-RPC, then HTTP+JSON, then gRPC; protocol version 1.0 first;
    otherwise card order.

    Raises:
        InterfaceNotFoundError: if ``url`` matches no interface, or the card has none.
    """
    interfaces = list(card.supported_interfaces)
    if url is not None:
        for iface in interfaces:
            if iface.url == url:
                return iface
        raise InterfaceNotFoundError(f"The agent card has no interface at {url}")
    if not interfaces:
        raise InterfaceNotFoundError("The agent card lists no supported interfaces")
    return min(interfaces, key=_rank)


def card_for_interface(card: AgentCard, iface: AgentInterface) -> AgentCard:
    """Return a copy of ``card`` whose only supported interface is ``iface``."""
    narrowed = AgentCard()
    narrowed.CopyFrom(card)
    del narrowed.supported_interfaces[:]
    narrowed.supported_interfaces.append(iface)
    return narrowed


async def open_client(
    card: AgentCard,
    iface: AgentInterface,
    sink: ExchangeSink,
    *,
    streaming: bool,
    faults: FaultProfile | None = None,
) -> Client:
    """Return an SDK client bound to ``iface``, recording all traffic to ``sink``.

    Streaming is used only when ``streaming`` is true and the card declares it.
    ``faults`` injects that profile's failures beneath the SDK. Closing the
    client closes its connections.

    Raises:
        UnsupportedBindingError: if ``iface`` uses a binding outside ``SUPPORTED_BINDINGS``.
    """
    if iface.protocol_binding not in SUPPORTED_BINDINGS:
        raise UnsupportedBindingError(f"{iface.protocol_binding} is not supported yet")
    config = ClientConfig(
        streaming=streaming,
        httpx_client=build_http_client(sink, faults=faults, binding=iface.protocol_binding),
        grpc_channel_factory=build_grpc_channel_factory(sink, faults=faults),
        supported_protocol_bindings=[iface.protocol_binding],
    )
    return ClientFactory(config).create(card_for_interface(card, iface))
