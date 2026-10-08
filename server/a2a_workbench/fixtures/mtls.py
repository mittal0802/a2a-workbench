"""A zoo agent whose A2A interfaces require a client certificate (mutual TLS)."""

import ssl
from types import TracebackType

from a2a_workbench.fixtures.certs import TestPki
from a2a_workbench.fixtures.runner import free_port
from a2a_workbench.fixtures.serve import ThreadServer
from a2a_workbench.fixtures.zoo import build_zoo_app


class MtlsZooServer:
    """Serves the card over plain HTTP and the A2A interfaces over HTTPS with client auth.

    ``card_url`` is the plain-HTTP card address; the card lists only the HTTPS
    interfaces.
    """

    def __init__(self, pki: TestPki) -> None:
        self.tls_port = free_port()
        tls_base = f"https://127.0.0.1:{self.tls_port}"
        app = build_zoo_app(tls_base, signed=False, auth="mtls")
        self._tls = ThreadServer(
            app,
            port=self.tls_port,
            scheme="https",
            ready_path="/.well-known/agent-card.json",
            uvicorn_options={
                "ssl_certfile": str(pki.server_cert_path),
                "ssl_keyfile": str(pki.server_key_path),
                "ssl_ca_certs": str(pki.ca_path),
                "ssl_cert_reqs": ssl.CERT_REQUIRED,
                "lifespan": "on",
            },
            verify=False,
        )
        self._card = ThreadServer(
            build_zoo_app(tls_base, signed=False, auth="mtls"),
            ready_path="/.well-known/agent-card.json",
            uvicorn_options={"lifespan": "on"},
        )
        self.card_url = ""
        self._pki = pki

    def _ready_tls(self) -> None:
        import time

        import httpx

        ctx = ssl.create_default_context(cadata=self._pki.ca_cert)
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            cert, key = os.path.join(tmp, "c.pem"), os.path.join(tmp, "k.pem")
            open(cert, "w").write(self._pki.client_cert)
            open(key, "w").write(self._pki.client_key)
            ctx.load_cert_chain(cert, key)
        for _ in range(100):
            try:
                httpx.get(
                    f"https://127.0.0.1:{self.tls_port}/.well-known/agent-card.json", verify=ctx
                )
                return
            except httpx.TransportError:
                time.sleep(0.05)
        raise RuntimeError("mTLS zoo did not start")

    def start(self) -> None:
        """Start both servers."""
        self._tls._thread.start()
        self._ready_tls()
        self._card.start()
        self.card_url = f"{self._card.base_url}/.well-known/agent-card.json"

    def stop(self) -> None:
        """Stop both servers."""
        self._card.stop()
        self._tls.stop()

    def __enter__(self) -> "MtlsZooServer":
        self.start()
        return self

    def __exit__(
        self, et: type[BaseException] | None, ev: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.stop()

    async def __aenter__(self) -> "MtlsZooServer":
        import asyncio

        await asyncio.to_thread(self.start)
        return self

    async def __aexit__(
        self, et: type[BaseException] | None, ev: BaseException | None, tb: TracebackType | None
    ) -> None:
        import asyncio

        await asyncio.to_thread(self.stop)
