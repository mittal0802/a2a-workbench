"""A one-shot local HTTP server that receives an OAuth browser redirect."""

import threading
from types import TracebackType
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from a2a_workbench.fixtures.serve import ThreadServer

_PAGE = """<!doctype html><meta charset=utf-8><title>A2A Workbench sign-in</title>
<p id=m>Finishing sign-in…</p><script>
if (location.hash.length > 1) {
  fetch("/oauth/fragment", {method: "POST", headers: {"content-type": "application/json"},
    body: JSON.stringify(Object.fromEntries(new URLSearchParams(location.hash.slice(1))))})
    .then(() => { document.getElementById("m").textContent = "Done. You can close this window."; });
} else { document.getElementById("m").textContent = "Done. You can close this window."; }
</script>"""


class CallbackServer:
    """Serves ``/oauth/callback`` on 127.0.0.1 and hands over the first redirect's parameters."""

    def __init__(self, port: int) -> None:
        self._params: dict[str, str] | None = None
        self._done = threading.Event()

        async def callback(request: Request) -> HTMLResponse:
            if request.query_params:
                self._deliver(dict(request.query_params))
            return HTMLResponse(_PAGE)

        async def fragment(request: Request) -> JSONResponse:
            self._deliver({k: str(v) for k, v in (await request.json()).items()})
            return JSONResponse({"ok": True})

        app = Starlette(
            routes=[
                Route("/oauth/callback", callback),
                Route("/oauth/fragment", fragment, methods=["POST"]),
            ]
        )
        self._server = ThreadServer(app, port=port, ready_path="/oauth/callback")
        self.redirect_uri = f"http://127.0.0.1:{port}/oauth/callback"

    def _deliver(self, params: dict[str, str]) -> None:
        if not self._done.is_set():
            self._params = params
            self._done.set()

    def wait(self, timeout: float) -> dict[str, str] | None:
        """Block until a redirect arrives (its parameters) or ``timeout`` passes (None)."""
        return self._params if self._done.wait(timeout) else None

    def __enter__(self) -> "CallbackServer":
        self._server.start()
        return self

    def __exit__(
        self, et: type[BaseException] | None, ev: BaseException | None, tb: TracebackType | None
    ) -> None:
        self._server.stop()

    def __call__(self, *_: Any) -> None:  # pragma: no cover
        return None
