"""Recording of every HTTP exchange made on behalf of the A2A SDK."""

import time
import uuid
import zlib
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

REDACTED = "••••"
SENSITIVE_HEADERS = frozenset(
    {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key"}
)
DEFAULT_MAX_BODY_BYTES = 1024 * 1024


@dataclass
class Frame:
    """One server-sent event, with its arrival time relative to the request start."""

    t_ms: float
    data: str


@dataclass
class Exchange:
    """A single HTTP request/response pair, with streamed frames for SSE responses."""

    id: str
    operation: str
    http_method: str
    url: str
    started_at: datetime
    request_headers: dict[str, str] = field(default_factory=dict)
    request_body: str | None = None
    status: int | None = None
    response_headers: dict[str, str] = field(default_factory=dict)
    response_body: str | None = None
    frames: list[Frame] = field(default_factory=list)
    duration_ms: float | None = None
    error: str | None = None
    truncated: bool = False
    agent_id: str | None = None
    conversation_id: str | None = None
    complete: bool = True

    def to_record(self) -> dict[str, Any]:
        """Return a JSON-serializable dict of every field."""
        data = asdict(self)
        data["started_at"] = self.started_at.isoformat()
        return data


ExchangeSink = Callable[[Exchange], Awaitable[None]]


@dataclass
class RecordingScope:
    """Labels attached to exchanges recorded while the scope is active."""

    operation: str
    agent_id: str | None = None
    conversation_id: str | None = None
    exchange_ids: list[str] = field(default_factory=list)


_current_scope: ContextVar[RecordingScope | None] = ContextVar("a2aw_recording_scope", default=None)


@contextmanager
def recording_scope(
    operation: str, *, agent_id: str | None = None, conversation_id: str | None = None
) -> Iterator[RecordingScope]:
    """Label exchanges recorded in this context and collect their ids."""
    scope = RecordingScope(operation, agent_id, conversation_id)
    token = _current_scope.set(scope)
    try:
        yield scope
    finally:
        _current_scope.reset(token)


def redact_headers(headers: httpx.Headers) -> dict[str, str]:
    """Return headers as a lowercase dict with credential-bearing values masked."""
    return {
        k.lower(): (REDACTED if k.lower() in SENSITIVE_HEADERS else v)
        for k, v in headers.multi_items()
    }


def _decoder(content_encoding: str) -> Any:
    encoding = content_encoding.strip().lower()
    if encoding == "gzip":
        return zlib.decompressobj(zlib.MAX_WBITS | 16)
    if encoding == "deflate":
        return zlib.decompressobj()
    return None


class _RecordingStream(httpx.AsyncByteStream):
    """Passes response bytes through unchanged while copying them into an Exchange."""

    def __init__(
        self,
        inner: httpx.AsyncByteStream,
        exchange: Exchange,
        started: float,
        sink: ExchangeSink,
        *,
        is_sse: bool,
        max_body_bytes: int,
        content_encoding: str,
    ) -> None:
        self._inner = inner
        self._ex = exchange
        self._started = started
        self._sink = sink
        self._is_sse = is_sse
        self._max = max_body_bytes
        self._encoding = content_encoding.strip().lower()
        self._decoder = _decoder(content_encoding)
        self._undecodable = bool(self._encoding) and self._decoder is None
        self._decode_error: str | None = None
        self._body = bytearray()
        self._sse_buffer = ""
        self._done = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        try:
            async for chunk in self._inner:
                try:
                    self._capture(chunk)
                except Exception as exc:  # the copy must never affect the caller
                    self._decode_error = f"{type(exc).__name__}: {exc}"
                    self._undecodable = True
                yield chunk
        except Exception as exc:
            self._ex.error = f"{type(exc).__name__}: {exc}"
            raise

    def _capture(self, chunk: bytes) -> None:
        if self._undecodable:
            return
        data = self._decompress(chunk) if self._decoder else chunk
        if self._is_sse:
            self._sse_buffer += data.decode("utf-8", errors="replace").replace("\r\n", "\n")
            while "\n\n" in self._sse_buffer:
                frame, self._sse_buffer = self._sse_buffer.split("\n\n", 1)
                if frame.strip():
                    self._ex.frames.append(Frame(self._elapsed(), frame))
        else:
            room = self._max - len(self._body)
            if len(data) > room:
                self._ex.truncated = True
            self._body.extend(data[: max(room, 0)])

    def _decompress(self, chunk: bytes) -> bytes:
        try:
            return bytes(self._decoder.decompress(chunk))
        except zlib.error:
            if self._encoding != "deflate" or self._body or self._sse_buffer:
                raise
            self._decoder = zlib.decompressobj(-zlib.MAX_WBITS)
            return bytes(self._decoder.decompress(chunk))

    def _elapsed(self) -> float:
        return round((time.perf_counter() - self._started) * 1000, 2)

    async def aclose(self) -> None:
        try:
            await self._inner.aclose()
        finally:
            await self._finish()

    async def _finish(self) -> None:
        if self._done:
            return
        self._done = True
        if self._is_sse and self._sse_buffer.strip():
            self._ex.frames.append(Frame(self._elapsed(), self._sse_buffer.strip()))
        if self._decode_error:
            self._ex.response_body = f"(body could not be decoded: {self._decode_error})"
        elif self._undecodable:
            self._ex.response_body = "(compressed body not decoded)"
        elif not self._is_sse:
            self._ex.response_body = self._body.decode("utf-8", errors="replace")
        self._ex.duration_ms = self._elapsed()
        self._ex.complete = True
        await self._sink(self._ex)


class RecordingTransport(httpx.AsyncBaseTransport):
    """httpx transport that records each request and response it carries.

    Bytes reach the caller unmodified. The record is handed to ``sink`` with
    ``complete=False`` when response headers arrive and again with
    ``complete=True`` once the body is closed; a failed request is handed over
    once, complete.
    """

    def __init__(
        self,
        sink: ExchangeSink,
        inner: httpx.AsyncBaseTransport | None = None,
        *,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    ) -> None:
        self._sink = sink
        self._inner = inner or httpx.AsyncHTTPTransport()
        self._max = max_body_bytes

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Forward ``request`` to the inner transport and record the exchange."""
        scope = _current_scope.get()
        exchange = Exchange(
            id=uuid.uuid4().hex,
            operation=scope.operation if scope else "http",
            http_method=request.method,
            url=str(request.url),
            started_at=datetime.now(UTC),
            request_headers=redact_headers(request.headers),
            request_body=self._request_body(request),
            agent_id=scope.agent_id if scope else None,
            conversation_id=scope.conversation_id if scope else None,
        )
        if scope:
            scope.exchange_ids.append(exchange.id)
        started = time.perf_counter()
        try:
            response = await self._inner.handle_async_request(request)
        except Exception as exc:
            exchange.error = f"{type(exc).__name__}: {exc}"
            exchange.duration_ms = round((time.perf_counter() - started) * 1000, 2)
            await self._sink(exchange)
            raise
        exchange.status = response.status_code
        exchange.response_headers = redact_headers(response.headers)
        exchange.complete = False
        await self._sink(exchange)
        stream = _RecordingStream(
            response.stream,  # type: ignore[arg-type]
            exchange,
            started,
            self._sink,
            is_sse=response.headers.get("content-type", "").startswith("text/event-stream"),
            max_body_bytes=self._max,
            content_encoding=response.headers.get("content-encoding", ""),
        )
        return httpx.Response(
            status_code=response.status_code,
            headers=response.headers,
            stream=stream,
            extensions=response.extensions,
            request=request,
        )

    def _request_body(self, request: httpx.Request) -> str | None:
        try:
            content = request.content
        except httpx.RequestNotRead:
            return "(streamed request body not recorded)"
        if not content:
            return None
        return content[: self._max].decode("utf-8", errors="replace")

    async def aclose(self) -> None:
        """Close the inner transport."""
        await self._inner.aclose()
