"""httpx clients configured for A2A traffic."""

import httpx

from a2a_workbench.core.auth.apply import TlsMaterial
from a2a_workbench.core.auth.tls import ssl_context
from a2a_workbench.core.connection.recorder import (
    DEFAULT_MAX_BODY_BYTES,
    ExchangeSink,
    RecordingTransport,
)
from a2a_workbench.core.faults.http import FaultTransport
from a2a_workbench.core.faults.injector import FaultInjector, as_injector
from a2a_workbench.core.faults.profile import FaultProfile

DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)


def build_http_client(
    sink: ExchangeSink,
    *,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    inner: httpx.AsyncBaseTransport | None = None,
    faults: FaultProfile | FaultInjector | None = None,
    binding: str = "HTTP",
    query: dict[str, str] | None = None,
    tls: TlsMaterial | None = None,
) -> httpx.AsyncClient:
    """Return an httpx client whose every exchange is recorded to ``sink``.

    With ``faults``, failures from that profile are injected between the
    recorder and the network, so recordings show them. ``query`` parameters
    are added to every request (and masked in recordings); ``tls`` presents a
    client certificate.
    """
    transport: httpx.AsyncBaseTransport = inner or httpx.AsyncHTTPTransport(
        verify=ssl_context(tls) if tls else True
    )
    injector = as_injector(faults)
    if injector is not None:
        transport = FaultTransport(transport, injector, binding=binding)
    return httpx.AsyncClient(
        transport=RecordingTransport(
            sink,
            transport,
            max_body_bytes=max_body_bytes,
            sensitive_query=frozenset(query or ()),
        ),
        params=query or None,
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=True,
    )
