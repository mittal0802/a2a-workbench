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
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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
    fault: str | None = None

    def to_record(self) -> dict[str, Any]:
        """Return a JSON-serializable dict of every field."""
        data = asdict(self)
        data["started_at"] = self.started_at.isoformat()
        return data


ExchangeSink = Callable[[Exchange], Awaitable[None]]


@dataclass
class RecordingScope:
    """Labels attached to exchanges recorded while the scope is active.

    ``redact_fields`` names form or JSON body fields whose values are masked
    in the recorded request and response bodies (at any depth); ``secrets``
    are values masked wherever they appear in bodies and stream frames.
    """

    operation: str
    agent_id: str | None = None
    conversation_id: str | None = None
    exchange_ids: list[str] = field(default_factory=list)
    redact_fields: frozenset[str] = frozenset()
    secrets: tuple[str, ...] = ()
    parent: "RecordingScope | None" = None

    def add(self, exchange_id: str) -> None:
        """Record ``exchange_id`` in this scope and every enclosing scope."""
        scope: RecordingScope | None = self
        while scope is not None:
            if exchange_id not in scope.exchange_ids:
                scope.exchange_ids.append(exchange_id)
            scope = scope.parent


_current_scope: ContextVar[RecordingScope | None] = ContextVar("a2aw_recording_scope", default=None)


@contextmanager
def recording_scope(
    operation: str,
    *,
    agent_id: str | None = None,
    conversation_id: str | None = None,
    redact_fields: frozenset[str] = frozenset(),
    secrets: tuple[str, ...] = (),
) -> Iterator[RecordingScope]:
    """Label exchanges recorded in this context and collect their ids."""
    parent = _current_scope.get()
    scope = RecordingScope(
        operation,
        agent_id,
        conversation_id,
        redact_fields=redact_fields | (parent.redact_fields if parent else frozenset()),
        secrets=secrets + (parent.secrets if parent else ()),
        parent=parent,
    )
    token = _current_scope.set(scope)
    try:
        yield scope
    finally:
        _current_scope.reset(token)


SENSITIVE_QUERY_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "api-key",
        "key",
        "token",
        "access_token",
        "id_token",
        "refresh_token",
        "password",
        "passwd",
        "secret",
        "client_secret",
        "code",
        "sig",
        "signature",
    }
)


def redact_url(url: str, extra_keys: frozenset[str] = frozenset()) -> str:
    """Return ``url`` with user info and credential-like query values masked.

    ``extra_keys`` names further query parameters to mask.
    """
    parts = urlsplit(url)
    netloc = parts.netloc
    if "@" in netloc:
        netloc = f"{REDACTED}@{netloc.rsplit('@', 1)[1]}"
    query = parts.query
    if query:
        pairs = parse_qsl(query, keep_blank_values=True)
        query = urlencode(
            [
                (k, REDACTED if k.lower() in SENSITIVE_QUERY_KEYS or k in extra_keys else v)
                for k, v in pairs
            ],
            safe=REDACTED,
        )
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


def redact_body(body: str | None, fields: frozenset[str]) -> str | None:
    """Return ``body`` with the values of ``fields`` masked in form-encoded or JSON content."""
    if not body or not fields:
        return body
    import json

    try:
        value = json.loads(body)
    except ValueError:
        value = None
    if isinstance(value, dict | list):

        def walk(node: Any) -> Any:
            if isinstance(node, dict):
                return {k: (REDACTED if k in fields else walk(v)) for k, v in node.items()}
            if isinstance(node, list):
                return [walk(v) for v in node]
            return node

        return json.dumps(walk(value))
    if "=" in body and "\n" not in body:
        pairs = parse_qsl(body, keep_blank_values=True)
        return urlencode([(k, REDACTED if k in fields else v) for k, v in pairs], safe=REDACTED)
    return body


def scrub_exchange(exchange: "Exchange") -> None:
    """Apply the active scope's field redaction and secret masking to ``exchange`` in place."""
    scope = _current_scope.get()
    if scope is None or not (scope.redact_fields or scope.secrets):
        return

    def clean(text: str | None) -> str | None:
        text = redact_body(text, scope.redact_fields)
        for secret in scope.secrets:
            if text and secret:
                text = text.replace(secret, REDACTED)
        return text

    exchange.request_body = clean(exchange.request_body)
    exchange.response_body = clean(exchange.response_body)
    for frame in exchange.frames:
        frame.data = clean(frame.data) or ""


def add_to_current_scope(exchange_ids: list[str]) -> None:
    """Attribute already recorded exchanges to the active scope (and its parents) too."""
    scope = _current_scope.get()
    if scope is not None:
        for exchange_id in exchange_ids:
            scope.add(exchange_id)


def current_exchange_ids() -> list[str]:
    """Ids of the exchanges recorded so far in the active scope (empty outside one)."""
    scope = _current_scope.get()
    return list(scope.exchange_ids) if scope else []


def current_operation() -> str | None:
    """Return the operation label of the active recording scope, if any."""
    scope = _current_scope.get()
    return scope.operation if scope else None


def redact_headers(headers: httpx.Headers, extra: frozenset[str] = frozenset()) -> dict[str, str]:
    """Return headers as a lowercase dict with credential-bearing values masked.

    ``extra`` holds further lowercase header names to mask, such as API-key
    headers named by an agent card.
    """
    return {
        k.lower(): (REDACTED if k.lower() in SENSITIVE_HEADERS or k.lower() in extra else v)
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
        redact: frozenset[str] = frozenset(),
    ) -> None:
        self._redact = redact
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
        self._ex.response_body = redact_body(self._ex.response_body, self._redact)
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
        sensitive_query: frozenset[str] = frozenset(),
        sensitive_headers: frozenset[str] = frozenset(),
    ) -> None:
        self._sink = sink
        self._inner = inner or httpx.AsyncHTTPTransport()
        self._max = max_body_bytes
        self._sensitive_query = sensitive_query
        self._sensitive_headers = frozenset(h.lower() for h in sensitive_headers)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Forward ``request`` to the inner transport and record the exchange."""
        scope = _current_scope.get()
        exchange = Exchange(
            id=uuid.uuid4().hex,
            operation=scope.operation if scope else "http",
            http_method=request.method,
            url=redact_url(str(request.url), self._sensitive_query),
            started_at=datetime.now(UTC),
            request_headers=redact_headers(request.headers, self._sensitive_headers),
            request_body=redact_body(
                self._request_body(request), scope.redact_fields if scope else frozenset()
            ),
            agent_id=scope.agent_id if scope else None,
            conversation_id=scope.conversation_id if scope else None,
        )
        if scope:
            scope.add(exchange.id)
        started = time.perf_counter()
        try:
            response = await self._inner.handle_async_request(request)
        except Exception as exc:
            exchange.error = f"{type(exc).__name__}: {exc}"
            exchange.fault = request.extensions.get("a2aw_fault")
            exchange.duration_ms = round((time.perf_counter() - started) * 1000, 2)
            await self._sink(exchange)
            raise
        exchange.fault = request.extensions.get("a2aw_fault")
        exchange.status = response.status_code
        exchange.response_headers = redact_headers(response.headers, self._sensitive_headers)
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
            redact=scope.redact_fields if scope else frozenset(),
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
