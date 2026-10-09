"""Protection of the local server against DNS rebinding and cross-site requests."""

from collections.abc import Iterable
from urllib.parse import urlsplit

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_ANY_HOST = frozenset({"0.0.0.0", "::", ""})


def _hostname(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("["):
        return value[1 : value.find("]")] if "]" in value else value[1:]
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def allowed_hosts(bind_host: str, extra: Iterable[str]) -> frozenset[str]:
    """Return the hostnames the server answers to: loopback, the bind host and ``extra``."""
    hosts = set(LOOPBACK_HOSTS)
    if bind_host not in _ANY_HOST:
        hosts.add(_hostname(bind_host))
    hosts.update(_hostname(h) for h in extra if h.strip())
    return frozenset(hosts)


class HostGuardMiddleware:
    """Rejects requests whose Host, or Origin when present, is not an allowed hostname.

    HTTP requests get 400 for a foreign Host and 403 for a foreign Origin;
    WebSocket handshakes from either are closed before acceptance. ``"*"`` in
    the allowed set disables the check. ``POST /hooks/*`` (agent webhooks, which
    authenticate every request themselves) is always let through.
    """

    def __init__(self, app: ASGIApp, hosts: frozenset[str]) -> None:
        self.app = app
        self.hosts = hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        hook = (
            scope["type"] == "http"
            and scope.get("method") == "POST"
            and str(scope.get("path", "")).startswith("/hooks/")
        )
        if scope["type"] not in ("http", "websocket") or "*" in self.hosts or hook:
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        host_ok = _hostname(headers.get("host", "")) in self.hosts
        origin = headers.get("origin")
        origin_ok = origin is None or (urlsplit(origin).hostname or "") in self.hosts
        if host_ok and origin_ok:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        status = 400 if not host_ok else 403
        reason = "Host not allowed" if not host_ok else "Origin not allowed"
        await PlainTextResponse(reason, status_code=status)(scope, receive, send)
