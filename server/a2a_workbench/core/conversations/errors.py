"""Classification of failures raised while talking to an agent."""

from collections.abc import Iterator
from typing import Any

import grpc
import httpx
from a2a.client import A2AClientError, A2AClientTimeoutError
from a2a.utils.errors import A2A_ERROR_MAPPING, JSON_RPC_ERROR_CODE_MAP, A2AError


def _chain(exc: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def classify_error(exc: BaseException) -> dict[str, Any]:
    """Return ``{"category", "message", ...}`` describing ``exc``.

    Categories: ``auth`` (HTTP 401/403), ``transport`` (network, TLS, timeouts),
    ``protocol`` (A2A errors, other HTTP errors, malformed responses) and
    ``workbench`` (anything else). A2A errors also carry ``code``, ``reason``
    and ``data``; HTTP errors carry ``http_status``; gRPC failures map
    UNAUTHENTICATED/PERMISSION_DENIED to ``auth`` and UNAVAILABLE/
    DEADLINE_EXCEEDED to ``transport`` and carry ``grpc_status``.
    """
    chain = list(_chain(exc))
    rpc = next((e for e in chain if isinstance(e, grpc.aio.AioRpcError)), None)
    if rpc is not None:
        code = rpc.code()
        base = {"message": str(exc), "grpc_status": code.name}
        if code in (grpc.StatusCode.UNAUTHENTICATED, grpc.StatusCode.PERMISSION_DENIED):
            return {"category": "auth", **base}
        if code in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED):
            return {"category": "transport", **base}
    status = next(
        (e.response.status_code for e in chain if isinstance(e, httpx.HTTPStatusError)), None
    )
    if status in (401, 403):
        return {"category": "auth", "message": str(exc), "http_status": status}
    if any(isinstance(e, A2AClientTimeoutError | httpx.TransportError) for e in chain):
        return {"category": "transport", "message": str(exc)}
    a2a = next(
        (e for e in chain if isinstance(e, A2AError) and not isinstance(e, A2AClientError)),
        None,
    )
    if a2a is not None:
        mapping = A2A_ERROR_MAPPING.get(type(a2a))
        return {
            "category": "protocol",
            "message": a2a.message,
            "code": JSON_RPC_ERROR_CODE_MAP.get(type(a2a)),
            "reason": mapping.reason if mapping else None,
            "data": a2a.data,
        }
    if rpc is not None:
        return {"category": "protocol", "message": str(exc), "grpc_status": rpc.code().name}
    if isinstance(exc, A2AClientError) or status is not None:
        out: dict[str, Any] = {"category": "protocol", "message": str(exc)}
        if status is not None:
            out["http_status"] = status
        return out
    return {"category": "workbench", "message": f"{type(exc).__name__}: {exc}"}
