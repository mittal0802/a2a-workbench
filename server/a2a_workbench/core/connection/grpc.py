"""gRPC channels for the A2A SDK, with every call recorded."""

import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import grpc
from google.protobuf.json_format import MessageToJson

from a2a_workbench.core.auth.apply import TlsMaterial
from a2a_workbench.core.auth.tls import grpc_credentials
from a2a_workbench.core.connection.grpc_call import UnaryStreamCallProxy, as_channel_interceptors
from a2a_workbench.core.connection.recorder import (
    REDACTED,
    SENSITIVE_HEADERS,
    Exchange,
    ExchangeSink,
    Frame,
    _current_scope,
)
from a2a_workbench.core.faults.grpc import FaultGrpcInterceptor, grpc_fault_label
from a2a_workbench.core.faults.injector import FaultInjector, as_injector
from a2a_workbench.core.faults.profile import FaultProfile

_DEFAULT_PORTS = {"https": 443, "grpcs": 443, "http": 80, "grpc": 80}


def parse_grpc_target(url: str) -> tuple[str, bool]:
    """Return ``(host:port, secure)`` for a gRPC interface URL.

    Accepts ``host:port`` or a URL with scheme ``grpc``/``http`` (plaintext)
    or ``grpcs``/``https`` (TLS); any path is ignored.
    """
    if "://" not in url:
        return url.strip().rstrip("/"), False
    parts = urlsplit(url.strip())
    secure = parts.scheme in ("https", "grpcs")
    port = parts.port or _DEFAULT_PORTS.get(parts.scheme, 443 if secure else 80)
    return f"{parts.hostname}:{port}", secure


def _method_name(details: Any) -> str:
    method = details.method
    return method.decode() if isinstance(method, bytes) else str(method)


def _metadata(details: Any, extra: frozenset[str] = frozenset()) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in details.metadata or ():
        k = key.lower()
        out[k] = REDACTED if k in SENSITIVE_HEADERS or k in extra else str(value)
    return out


def _status(code: grpc.StatusCode) -> int:
    return int(code.value[0])


class RecordingGrpcInterceptor:
    """Records each unary and server-streaming call as an ``Exchange``.

    The URL is ``grpc://<target><method>``, ``status`` is the numeric gRPC
    status code, the request and each response message are stored as JSON,
    and streamed messages become frames.
    """

    def __init__(
        self, sink: ExchangeSink, target: str, sensitive_headers: frozenset[str] = frozenset()
    ) -> None:
        self._sensitive = frozenset(h.lower() for h in sensitive_headers)
        self._sink = sink
        self._target = target

    def _start(self, details: Any, request: Any) -> Exchange:
        scope = _current_scope.get()
        exchange = Exchange(
            id=uuid.uuid4().hex,
            operation=scope.operation if scope else "grpc",
            http_method="GRPC",
            url=f"grpc://{self._target}{_method_name(details)}",
            started_at=datetime.now(UTC),
            request_headers=_metadata(details, self._sensitive),
            request_body=MessageToJson(request),
            agent_id=scope.agent_id if scope else None,
            conversation_id=scope.conversation_id if scope else None,
            complete=False,
        )
        if scope:
            scope.add(exchange.id)
        return exchange

    async def _finish(
        self, exchange: Exchange, started: float, label: dict[str, str], error: BaseException | None
    ) -> None:
        exchange.duration_ms = round((time.perf_counter() - started) * 1000, 2)
        exchange.fault = label.get("fault")
        if isinstance(error, grpc.aio.AioRpcError):
            exchange.status = _status(error.code())
            exchange.error = f"{error.code().name}: {error.details()}"
        elif error is not None:
            exchange.error = f"{type(error).__name__}: {error}"
        else:
            exchange.status = 0
        exchange.complete = True
        await self._sink(exchange)

    async def intercept_unary_unary(
        self, continuation: Any, client_call_details: Any, request: Any
    ) -> Any:
        """Record one unary call."""
        exchange = self._start(client_call_details, request)
        label: dict[str, str] = {}
        token = grpc_fault_label.set(label)
        started = time.perf_counter()
        try:
            response = await (await continuation(client_call_details, request))
        except BaseException as exc:
            await self._finish(exchange, started, label, exc)
            raise
        finally:
            grpc_fault_label.reset(token)
        exchange.response_body = MessageToJson(response)
        await self._finish(exchange, started, label, None)
        return response

    async def intercept_unary_stream(
        self, continuation: Any, client_call_details: Any, request: Any
    ) -> Any:
        """Record one server-streaming call, one frame per message."""
        exchange = self._start(client_call_details, request)
        label: dict[str, str] = {}
        token = grpc_fault_label.set(label)
        started = time.perf_counter()
        try:
            call = await continuation(client_call_details, request)
        except BaseException as exc:
            grpc_fault_label.reset(token)
            await self._finish(exchange, started, label, exc)
            raise
        grpc_fault_label.reset(token)
        await self._sink(exchange)

        async def on_message(message: Any) -> Any:
            elapsed = round((time.perf_counter() - started) * 1000, 2)
            exchange.frames.append(Frame(elapsed, MessageToJson(message)))
            return message

        async def on_end(error: BaseException | None) -> None:
            await self._finish(exchange, started, label, error)

        return UnaryStreamCallProxy(call, on_message=on_message, on_end=on_end)


def build_grpc_channel_factory(
    sink: ExchangeSink,
    *,
    faults: FaultProfile | FaultInjector | None = None,
    tls: TlsMaterial | None = None,
    sensitive_headers: frozenset[str] = frozenset(),
) -> Callable[[str], grpc.aio.Channel]:
    """Return a factory creating recorded (and optionally fault-injected) channels.

    ``tls`` makes every channel TLS with that client certificate.
    """
    injector = as_injector(faults)

    def factory(url: str) -> grpc.aio.Channel:
        target, secure = parse_grpc_target(url)
        interceptors = as_channel_interceptors(
            RecordingGrpcInterceptor(sink, target, sensitive_headers)
        )
        if injector is not None:
            interceptors += as_channel_interceptors(FaultGrpcInterceptor(injector))
        if tls is not None:
            return grpc.aio.secure_channel(target, grpc_credentials(tls), interceptors=interceptors)
        if secure:
            return grpc.aio.secure_channel(
                target, grpc.ssl_channel_credentials(), interceptors=interceptors
            )
        return grpc.aio.insecure_channel(target, interceptors=interceptors)

    return factory
