"""httpx clients configured for A2A traffic."""

import httpx

from a2a_workbench.core.connection.recorder import (
    DEFAULT_MAX_BODY_BYTES,
    ExchangeSink,
    RecordingTransport,
)
from a2a_workbench.core.faults.http import FaultTransport
from a2a_workbench.core.faults.injector import FaultInjector
from a2a_workbench.core.faults.profile import FaultProfile

DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)


def build_http_client(
    sink: ExchangeSink,
    *,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    inner: httpx.AsyncBaseTransport | None = None,
    faults: FaultProfile | None = None,
    binding: str = "HTTP",
) -> httpx.AsyncClient:
    """Return an httpx client whose every exchange is recorded to ``sink``.

    With ``faults``, failures from that profile are injected between the
    recorder and the network, so recordings show them.
    """
    transport: httpx.AsyncBaseTransport = inner or httpx.AsyncHTTPTransport()
    if faults is not None:
        transport = FaultTransport(transport, FaultInjector(faults), binding=binding)
    return httpx.AsyncClient(
        transport=RecordingTransport(sink, transport, max_body_bytes=max_body_bytes),
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=True,
    )
