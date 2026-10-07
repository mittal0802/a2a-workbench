"""httpx clients configured for A2A traffic."""

import httpx

from a2a_workbench.core.connection.recorder import (
    DEFAULT_MAX_BODY_BYTES,
    ExchangeSink,
    RecordingTransport,
)

DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)


def build_http_client(
    sink: ExchangeSink,
    *,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    inner: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    """Return an httpx client whose every exchange is recorded to ``sink``."""
    return httpx.AsyncClient(
        transport=RecordingTransport(sink, inner, max_body_bytes=max_body_bytes),
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=True,
    )
