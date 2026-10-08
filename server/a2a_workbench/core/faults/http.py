"""httpx transport that injects network failures beneath the A2A SDK."""

import asyncio
import time
from collections.abc import AsyncIterator

import httpx

from a2a_workbench.core.connection.recorder import current_operation
from a2a_workbench.core.faults.injector import FaultInjector
from a2a_workbench.core.faults.profile import FaultRule

FAULT_EXTENSION = "a2aw_fault"


class _FaultStream(httpx.AsyncByteStream):
    """Response body wrapper that breaks, cuts or corrupts the bytes it passes on."""

    def __init__(self, inner: httpx.AsyncByteStream, rule: FaultRule) -> None:
        self._inner = inner
        self._rule = rule

    async def __aiter__(self) -> AsyncIterator[bytes]:
        kind, params = self._rule.kind, self._rule.params
        if kind == "reset":
            raise httpx.ReadError("[injected] connection reset by peer")
        if kind == "truncate":
            remaining = int(params["bytes"])
            async for chunk in self._inner:
                if remaining <= 0:
                    break
                yield chunk[:remaining]
                remaining -= len(chunk)
            return
        if kind == "garble":
            async for chunk in self._inner:
                yield bytes(b ^ 0x5A if i % 3 == 1 else b for i, b in enumerate(chunk))
            return
        if kind == "drop_stream":
            async for chunk in self._drop(params):
                yield chunk
            return
        async for chunk in self._inner:
            yield chunk

    async def _drop(self, params: dict[str, object]) -> AsyncIterator[bytes]:
        after_events = params.get("after_events")
        after_ms = params.get("after_ms")
        started = time.monotonic()
        if after_events == 0:
            raise httpx.ReadError("[injected] stream dropped")
        buffer = b""
        events = 0
        async for chunk in self._inner:
            buffer += chunk.replace(b"\r\n", b"\n")
            while b"\n\n" in buffer:
                frame, buffer = buffer.split(b"\n\n", 1)
                yield frame + b"\n\n"
                events += 1
                if isinstance(after_events, int) and events >= after_events:
                    raise httpx.ReadError(f"[injected] stream dropped after {events} events")
            if isinstance(after_ms, int) and (time.monotonic() - started) * 1000 >= after_ms:
                raise httpx.ReadError(f"[injected] stream dropped after {after_ms} ms")
        if buffer:
            yield buffer

    async def aclose(self) -> None:
        await self._inner.aclose()


class FaultTransport(httpx.AsyncBaseTransport):
    """Forwards requests to ``inner`` unless the injector picks a fault for the call.

    The applied fault kind is stored in ``request.extensions["a2aw_fault"]``.
    Faults act on connections and bytes only; request content is never changed.
    """

    def __init__(
        self, inner: httpx.AsyncBaseTransport, injector: FaultInjector, *, binding: str
    ) -> None:
        self._inner = inner
        self._injector = injector
        self._binding = binding

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Apply the selected fault, if any, around forwarding ``request``."""
        rule = self._injector.decide(current_operation() or "http", self._binding)
        if rule is None:
            return await self._inner.handle_async_request(request)
        request.extensions[FAULT_EXTENSION] = rule.kind
        kind, params = rule.kind, rule.params
        if kind == "refuse":
            raise httpx.ConnectError("[injected] connection refused", request=request)
        if kind == "dns_fail":
            raise httpx.ConnectError("[injected] name resolution failed", request=request)
        if kind == "tls_fail":
            raise httpx.ConnectError("[injected] TLS handshake failed", request=request)
        if kind == "connect_timeout":
            raise httpx.ConnectTimeout("[injected] connect timeout", request=request)
        if kind == "read_timeout":
            await asyncio.sleep(int(params.get("after_ms", 0)) / 1000)
            raise httpx.ReadTimeout("[injected] read timeout", request=request)
        if kind == "http_status":
            headers = {"content-type": "text/plain"}
            if "retry_after" in params:
                headers["retry-after"] = str(params["retry_after"])
            return httpx.Response(
                int(params["code"]),
                headers=headers,
                content=f"[injected] HTTP {params['code']}".encode(),
                request=request,
            )
        if kind == "expire_token":
            return httpx.Response(
                401,
                headers={
                    "www-authenticate": 'Bearer error="invalid_token", '
                    'error_description="The access token expired (injected)"'
                },
                content=b"[injected] token expired",
                request=request,
            )
        if kind == "delay":
            await asyncio.sleep(int(params["ms"]) / 1000)
            return await self._inner.handle_async_request(request)
        response = await self._inner.handle_async_request(request)
        headers = [
            (k, v) for k, v in response.headers.multi_items() if k.lower() != "content-length"
        ]
        return httpx.Response(
            response.status_code,
            headers=headers,
            stream=_FaultStream(response.stream, rule),  # type: ignore[arg-type]
            extensions=response.extensions,
            request=request,
        )

    async def aclose(self) -> None:
        """Close the inner transport."""
        await self._inner.aclose()
