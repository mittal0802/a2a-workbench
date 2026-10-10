"""Run zoo agents on a free local port in a background thread."""

import asyncio
import socket
import threading
import time
from types import TracebackType
from typing import Any

import httpx
import uvicorn

from a2a_workbench.fixtures.zoo import build_zoo_app


def free_port(host: str = "127.0.0.1") -> int:
    """Return a TCP port that is currently free on ``host``."""
    with socket.socket() as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


class ZooServer:
    """Serves the zoo agent with uvicorn in a daemon thread while the context is open."""

    def __init__(
        self,
        *,
        signed: bool = True,
        host: str = "127.0.0.1",
        port: int | None = None,
        card_path: str = "/.well-known/agent-card.json",
        grpc: bool = True,
        legacy: bool = False,
        auth: str = "none",
        idp: Any = None,
        extended_configured: bool = True,
        push: bool = True,
        breaks: frozenset[str] | set[str] = frozenset(),
        streaming: bool = True,
        required_extension: bool = False,
    ) -> None:
        self.host = host
        self.port = port or free_port(host)
        self.base_url = f"http://{host}:{self.port}"
        self.card_path = card_path
        self.grpc_port = free_port(host) if grpc else None
        app = build_zoo_app(
            self.base_url,
            signed=signed,
            card_path=card_path,
            grpc_port=self.grpc_port,
            legacy=legacy,
            auth=auth,
            idp=idp,
            extended_configured=extended_configured,
            push=push,
            breaks=frozenset(breaks),
            streaming=streaming,
            required_extension=required_extension,
        )
        self._server = uvicorn.Server(
            uvicorn.Config(app, host=host, port=self.port, log_level="warning", lifespan="on")
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def start(self, timeout: float = 10.0) -> None:
        """Start serving and block until the card endpoint answers."""
        self._thread.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                httpx.get(f"{self.base_url}{self.card_path}", timeout=0.5)
                return
            except httpx.TransportError:
                time.sleep(0.05)
        raise RuntimeError(f"zoo agent did not start on {self.base_url}")

    def stop(self) -> None:
        """Ask the server to exit and wait for its thread."""
        self._server.should_exit = True
        self._thread.join(timeout=5)

    def __enter__(self) -> "ZooServer":
        self.start()
        return self

    def __exit__(
        self,
        et: type[BaseException] | None,
        ev: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()

    async def __aenter__(self) -> "ZooServer":
        await asyncio.to_thread(self.start)
        return self

    async def __aexit__(
        self,
        et: type[BaseException] | None,
        ev: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await asyncio.to_thread(self.stop)
