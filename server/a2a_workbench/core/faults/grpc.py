"""grpc.aio client interceptor that injects network failures beneath the A2A SDK."""

import asyncio
import time
from contextvars import ContextVar
from typing import Any

import grpc

from a2a_workbench.core.connection.grpc_call import UnaryStreamCallProxy
from a2a_workbench.core.connection.recorder import current_operation
from a2a_workbench.core.faults.injector import FaultInjector
from a2a_workbench.core.faults.profile import FaultRule

# Set by the recording interceptor around each call; the fault interceptor writes
# the applied fault kind into it so the recorded exchange can be labelled.
grpc_fault_label: ContextVar[dict[str, str] | None] = ContextVar("a2aw_grpc_fault", default=None)

_HTTP_TO_GRPC = {
    400: grpc.StatusCode.INVALID_ARGUMENT,
    401: grpc.StatusCode.UNAUTHENTICATED,
    403: grpc.StatusCode.PERMISSION_DENIED,
    404: grpc.StatusCode.NOT_FOUND,
    409: grpc.StatusCode.ABORTED,
    429: grpc.StatusCode.RESOURCE_EXHAUSTED,
    500: grpc.StatusCode.INTERNAL,
    501: grpc.StatusCode.UNIMPLEMENTED,
    503: grpc.StatusCode.UNAVAILABLE,
    504: grpc.StatusCode.DEADLINE_EXCEEDED,
}


def _rpc_error(code: grpc.StatusCode, details: str) -> grpc.aio.AioRpcError:
    return grpc.aio.AioRpcError(code, grpc.aio.Metadata(), grpc.aio.Metadata(), details)


def _label(kind: str) -> None:
    label = grpc_fault_label.get()
    if label is not None:
        label["fault"] = kind


def _error_for(rule: FaultRule) -> grpc.aio.AioRpcError | None:
    kind, params = rule.kind, rule.params
    unavailable = {
        "refuse": "connection refused",
        "dns_fail": "name resolution failed",
        "tls_fail": "TLS handshake failed",
        "reset": "connection reset by peer",
    }
    if kind in unavailable:
        return _rpc_error(grpc.StatusCode.UNAVAILABLE, f"[injected] {unavailable[kind]}")
    if kind in ("connect_timeout", "read_timeout"):
        return _rpc_error(grpc.StatusCode.DEADLINE_EXCEEDED, f"[injected] {kind}")
    if kind == "http_status":
        code = int(params["code"])
        status = _HTTP_TO_GRPC.get(
            code, grpc.StatusCode.INTERNAL if code >= 500 else grpc.StatusCode.UNKNOWN
        )
        return _rpc_error(status, f"[injected] status equivalent to HTTP {code}")
    if kind == "expire_token":
        return _rpc_error(grpc.StatusCode.UNAUTHENTICATED, "[injected] access token expired")
    return None


class FaultGrpcInterceptor(
    grpc.aio.UnaryUnaryClientInterceptor, grpc.aio.UnaryStreamClientInterceptor
):
    """Applies the injector's decision to each unary and server-streaming call.

    Connection-level kinds fail the call with the equivalent gRPC status before
    it is sent; ``delay`` waits first; ``drop_stream`` fails a stream after the
    configured number of messages or milliseconds. Byte-level kinds
    (``truncate``, ``garble``) have no gRPC equivalent and are labelled as not
    applicable without effect.
    """

    def __init__(self, injector: FaultInjector) -> None:
        self._injector = injector

    async def _before(self) -> FaultRule | None:
        rule = self._injector.decide(current_operation() or "grpc", "GRPC")
        if rule is None:
            return None
        if rule.kind in ("truncate", "garble"):
            _label(f"{rule.kind}(not applicable)")
            return None
        _label(rule.kind)
        if rule.kind == "read_timeout":
            await asyncio.sleep(int(rule.params.get("after_ms", 0)) / 1000)
        error = _error_for(rule)
        if error is not None:
            raise error
        if rule.kind == "delay":
            await asyncio.sleep(int(rule.params["ms"]) / 1000)
        return rule

    async def intercept_unary_unary(
        self, continuation: Any, client_call_details: Any, request: Any
    ) -> Any:
        """Inject a fault, if one is selected, around a unary call."""
        await self._before()
        return await continuation(client_call_details, request)

    async def intercept_unary_stream(
        self, continuation: Any, client_call_details: Any, request: Any
    ) -> Any:
        """Inject a fault, if one is selected, around a server-streaming call."""
        rule = await self._before()
        call = await continuation(client_call_details, request)
        if rule is None or rule.kind != "drop_stream":
            return call
        return self._drop(call, rule)

    def _drop(self, call: Any, rule: FaultRule) -> UnaryStreamCallProxy:
        after_events = rule.params.get("after_events")
        after_ms = rule.params.get("after_ms")
        started = time.monotonic()
        delivered = 0

        async def before_read() -> None:
            elapsed = (time.monotonic() - started) * 1000
            if (isinstance(after_events, int) and delivered >= after_events) or (
                isinstance(after_ms, int) and elapsed >= after_ms
            ):
                call.cancel()
                raise _rpc_error(
                    grpc.StatusCode.UNAVAILABLE,
                    f"[injected] stream dropped after {delivered} events",
                )

        async def on_message(message: Any) -> Any:
            nonlocal delivered
            delivered += 1
            return message

        def read_timeout() -> float | None:
            if not isinstance(after_ms, int):
                return None
            return after_ms / 1000 - (time.monotonic() - started)

        def on_timeout() -> BaseException:
            return _rpc_error(
                grpc.StatusCode.UNAVAILABLE, f"[injected] stream dropped after {after_ms} ms"
            )

        return UnaryStreamCallProxy(
            call,
            before_read=before_read,
            on_message=on_message,
            read_timeout=read_timeout,
            on_timeout=on_timeout,
        )
