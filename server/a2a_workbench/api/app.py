"""FastAPI application: JSON API, WebSocket and the single-page app."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from a2a_workbench import __version__
from a2a_workbench.api import (
    routes_agents,
    routes_assistant,
    routes_conversations,
    routes_hooks,
    routes_misc,
    routes_oauth,
    routes_push,
    routes_security,
    routes_tasks,
    ws,
)
from a2a_workbench.api.errors import error_response, install_error_handlers
from a2a_workbench.api.host_guard import HostGuardMiddleware, allowed_hosts
from a2a_workbench.core.config import Settings
from a2a_workbench.core.workbench import Workbench

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def create_app(settings: Settings | None = None, *, static_dir: Path = STATIC_DIR) -> FastAPI:
    """Return the Workbench web application bound to ``settings``.

    Background sends are cancelled and awaited on shutdown.
    """
    settings = settings or Settings()
    workbench = Workbench(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await workbench.start()
        await workbench.announce_serving()
        try:
            yield
        finally:
            for task in list(app.state.tasks):
                task.cancel()
            await asyncio.gather(*app.state.tasks, return_exceptions=True)
            await workbench.close()

    app = FastAPI(title="A2A Workbench", version=__version__, lifespan=lifespan)
    app.state.workbench = workbench
    app.state.tasks = set()
    app.add_middleware(
        HostGuardMiddleware, hosts=allowed_hosts(settings.host, settings.extra_allowed_hosts)
    )
    install_error_handlers(app)
    for module in (
        routes_misc,
        routes_agents,
        routes_conversations,
        routes_tasks,
        routes_security,
        routes_oauth,
        routes_assistant,
        routes_hooks,
        routes_push,
        ws,
    ):
        app.include_router(module.router)
    _mount_spa(app, static_dir)
    return app


def _mount_spa(app: FastAPI, static_dir: Path) -> None:
    root = static_dir.resolve()
    index = root / "index.html"
    if (static_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Response:
        if path == "api" or path.startswith(("api/", "ws", "oauth/")):
            return error_response(404, {"category": "workbench", "message": "not found"})
        candidate = (root / path).resolve()
        if path and candidate.is_file() and root in candidate.parents:
            return FileResponse(candidate)
        if index.is_file():
            return FileResponse(index)
        return JSONResponse(
            {
                "error": {
                    "category": "workbench",
                    "message": "Web UI not built; run scripts/build.sh",
                }
            },
            status_code=404,
        )
