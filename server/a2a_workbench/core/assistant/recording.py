"""Records every HTTP exchange an LLM provider SDK makes, with API keys masked."""

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from a2a_workbench.core.connection.recorder import REDACTED, Exchange, ExchangeSink, redact_url

SECRET_HEADERS = frozenset({"authorization", "x-api-key", "x-goog-api-key", "api-key", "cookie"})
MAX_BODY = 2 * 1024 * 1024


def _decode(content: bytes) -> str:
    text = content[:MAX_BODY].decode("utf-8", errors="replace")
    return text


class LLMRecorder:
    """Event hooks for an httpx-style client (httpx or httpx2) that store each call as an exchange.

    Exchanges get operation ``llm_call`` and ``conversation_id`` set to the
    Assistant chat id. Secret headers and the ``key`` query parameter are
    masked, and ``secrets`` (such as the API key) are masked in bodies.
    ``last_id`` is the id of the most recent exchange.
    """

    def __init__(
        self, sink: ExchangeSink, *, session_id: str | None, secrets: tuple[str, ...] = ()
    ) -> None:
        self._sink = sink
        self._session = session_id
        self._secrets = tuple(s for s in secrets if s)
        self._started: dict[int, tuple[str, float, datetime]] = {}
        self.last_id: str | None = None

    def with_secret(self, secret: str) -> "LLMRecorder":
        """Return this recorder, also masking ``secret`` in bodies."""
        if secret:
            self._secrets = (*self._secrets, secret)
        return self

    def _scrub(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, REDACTED)
        return text

    def _headers(self, headers: Any) -> dict[str, str]:
        return {
            k.lower(): REDACTED if k.lower() in SECRET_HEADERS else self._scrub(v)
            for k, v in headers.items()
        }

    def hooks(self) -> dict[str, list[Any]]:
        """Return ``event_hooks`` for an async client."""

        async def on_request(request: Any) -> None:
            self._started[id(request)] = (uuid.uuid4().hex, time.monotonic(), datetime.now(UTC))

        async def on_response(response: Any) -> None:
            request = response.request
            exchange_id, t0, started = self._started.pop(
                id(request), (uuid.uuid4().hex, time.monotonic(), datetime.now(UTC))
            )
            await response.aread()
            self.last_id = exchange_id
            await self._sink(
                Exchange(
                    id=exchange_id,
                    operation="llm_call",
                    http_method=request.method,
                    url=self._scrub(redact_url(str(request.url), frozenset({"key"}))),
                    started_at=started,
                    request_headers=self._headers(request.headers),
                    request_body=self._scrub(_decode(request.content or b"")),
                    status=response.status_code,
                    response_headers=self._headers(response.headers),
                    response_body=self._scrub(_decode(response.content or b"")),
                    duration_ms=round((time.monotonic() - t0) * 1000, 1),
                    truncated=len(response.content or b"") > MAX_BODY,
                    conversation_id=self._session,
                )
            )

        return {"request": [on_request], "response": [on_response]}
