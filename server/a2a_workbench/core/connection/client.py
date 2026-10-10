"""Construction of A2A SDK clients for a chosen agent interface."""

from contextvars import ContextVar

from a2a.client import Client, ClientConfig, ClientFactory
from a2a.types import AgentCard, AgentInterface

from a2a_workbench.core.auth.apply import AuthPlan
from a2a_workbench.core.connection.grpc import build_grpc_channel_factory
from a2a_workbench.core.connection.http import build_http_client
from a2a_workbench.core.connection.recorder import ExchangeSink
from a2a_workbench.core.faults.injector import FaultInjector, as_injector
from a2a_workbench.core.faults.profile import FaultProfile

SUPPORTED_BINDINGS = ("JSONRPC", "HTTP+JSON", "GRPC")


class InterfaceNotFoundError(LookupError):
    """Raised when the card has no interface with the requested URL."""


class UnsupportedBindingError(ValueError):
    """Raised when an interface uses a protocol binding this build cannot speak."""


SUPPORTED_VERSIONS = ("1.0", "0.3")


def supported(iface: AgentInterface) -> bool:
    """Whether this client can use ``iface`` (binding and protocol version)."""
    version = iface.protocol_version or "1.0"
    return iface.protocol_binding in SUPPORTED_BINDINGS and any(
        version == v or version.startswith(f"{v}.") for v in SUPPORTED_VERSIONS
    )


interface_override: ContextVar[str | None] = ContextVar("a2aw_interface_override", default=None)
"""When set, ``select_interface`` uses this interface URL instead of the one asked for."""


def select_interface(card: AgentCard, url: str | None) -> AgentInterface:
    """Return the interface at ``url`` (or ``interface_override``), else the preferred one.

    Without a URL, the first interface in the card's order that this client
    supports is used (A2A §8.3.2: the first entry is the agent's preference).

    Raises:
        InterfaceNotFoundError: if ``url`` matches no interface, or the card has none.
    """
    interfaces = list(card.supported_interfaces)
    url = interface_override.get() or url
    if url is not None:
        for iface in interfaces:
            if iface.url == url:
                return iface
        raise InterfaceNotFoundError(f"The agent card has no interface at {url}")
    if not interfaces:
        raise InterfaceNotFoundError("The agent card lists no supported interfaces")
    for iface in interfaces:
        if supported(iface):
            return iface
    raise InterfaceNotFoundError(
        "None of the card's interfaces uses a binding and version this client supports "
        f"({', '.join(SUPPORTED_BINDINGS)}; A2A {', '.join(SUPPORTED_VERSIONS)})"
    )


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
    faults: FaultProfile | FaultInjector | None = None,
    auth: AuthPlan | None = None,
) -> Client:
    """Return an SDK client bound to ``iface``, recording all traffic to ``sink``.

    Streaming is used only when ``streaming`` is true and the card declares it.
    ``faults`` injects failures beneath the SDK; pass the same injector to
    several clients to share its rule state. ``auth`` adds the plan's query
    parameters and TLS client certificate to the transports; its headers are
    sent per call through ``ClientCallContext.service_parameters`` and masked
    in recordings. Closing the
    client closes its connections.

    Raises:
        UnsupportedBindingError: if ``iface`` uses a binding outside ``SUPPORTED_BINDINGS``.
    """
    if iface.protocol_binding not in SUPPORTED_BINDINGS:
        raise UnsupportedBindingError(f"{iface.protocol_binding} is not supported yet")
    injector = as_injector(faults)
    sensitive = frozenset(k.lower() for k in auth.headers) if auth else frozenset()
    config = ClientConfig(
        streaming=streaming,
        httpx_client=build_http_client(
            sink,
            faults=injector,
            binding=iface.protocol_binding,
            query=auth.query if auth else None,
            tls=auth.tls if auth else None,
            sensitive_headers=sensitive,
        ),
        grpc_channel_factory=build_grpc_channel_factory(
            sink, faults=injector, tls=auth.tls if auth else None, sensitive_headers=sensitive
        ),
        supported_protocol_bindings=[iface.protocol_binding],
    )
    return ClientFactory(config).create(card_for_interface(card, iface))
