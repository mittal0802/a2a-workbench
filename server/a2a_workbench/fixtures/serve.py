"""Serve any ASGI app on a free local port in a background thread."""

import asyncio
import threading
import time
from types import TracebackType
from typing import Any

import httpx
import uvicorn

from a2a_workbench.fixtures.runner import free_port


class ThreadServer:
    """Runs an ASGI app with uvicorn in a daemon thread while the context is open.

    ``ready_path`` is polled until it answers; ``uvicorn_options`` are passed
    through (e.g. TLS settings).
    """

    def __init__(
        self,
        app: Any,
        *,
        host: str = "127.0.0.1",
        port: int | None = None,
        ready_path: str = "/",
        scheme: str = "http",
        uvicorn_options: dict[str, Any] | None = None,
        verify: Any = True,
    ) -> None:
        self.port = port or free_port(host)
        self.base_url = f"{scheme}://{host}:{self.port}"
        self._ready = ready_path
        self._verify = verify
        config = uvicorn.Config(
            app, host=host, port=self.port, log_level="warning", **(uvicorn_options or {})
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def start(self, timeout: float = 10.0) -> None:
        """Start serving and block until ``ready_path`` answers."""
        self._thread.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                httpx.get(f"{self.base_url}{self._ready}", timeout=0.5, verify=self._verify)
                return
            except httpx.TransportError:
                time.sleep(0.05)
        raise RuntimeError(f"server did not start on {self.base_url}")

    def stop(self) -> None:
        """Ask the server to exit and wait for its thread."""
        self._server.should_exit = True
        self._thread.join(timeout=5)

    def __enter__(self) -> "ThreadServer":
        self.start()
        return self

    def __exit__(
        self, et: type[BaseException] | None, ev: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.stop()

    async def __aenter__(self) -> "ThreadServer":
        await asyncio.to_thread(self.start)
        return self

    async def __aexit__(
        self, et: type[BaseException] | None, ev: BaseException | None, tb: TracebackType | None
    ) -> None:
        await asyncio.to_thread(self.stop)
