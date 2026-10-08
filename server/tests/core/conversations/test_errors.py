import httpx
from a2a.client import A2AClientError, A2AClientTimeoutError
from a2a.utils.errors import TaskNotCancelableError

from a2a_workbench.core.conversations.errors import classify_error


def _wrapped(status):
    req = httpx.Request("POST", "http://x")
    try:
        try:
            httpx.Response(status, request=req).raise_for_status()
        except httpx.HTTPStatusError as e:
            raise A2AClientError(f"HTTP Error {status}") from e
    except A2AClientError as outer:
        return outer


def test_auth_from_401():
    assert classify_error(_wrapped(401))["category"] == "auth"


def test_auth_from_403():
    assert classify_error(_wrapped(403))["http_status"] == 403


def test_protocol_from_500():
    out = classify_error(_wrapped(500))
    assert out["category"] == "protocol" and out["http_status"] == 500


def test_transport_from_connect_error():
    try:
        try:
            raise httpx.ConnectError("refused")
        except httpx.ConnectError as e:
            raise A2AClientError("Network communication error") from e
    except A2AClientError as exc:
        assert classify_error(exc)["category"] == "transport"


def test_transport_from_timeout():
    assert classify_error(A2AClientTimeoutError("t"))["category"] == "transport"


def test_protocol_error_has_code_and_reason():
    out = classify_error(TaskNotCancelableError())
    assert out == {
        "category": "protocol",
        "message": "Task cannot be canceled",
        "code": -32002,
        "reason": "TASK_NOT_CANCELABLE",
        "data": None,
    }


def test_unknown_is_workbench():
    assert classify_error(RuntimeError("boom"))["category"] == "workbench"


def test_grpc_codes():
    import grpc

    def err(code):
        return grpc.aio.AioRpcError(code, grpc.aio.Metadata(), grpc.aio.Metadata(), "x")

    assert classify_error(err(grpc.StatusCode.UNAVAILABLE))["category"] == "transport"
    assert classify_error(err(grpc.StatusCode.DEADLINE_EXCEEDED))["category"] == "transport"
    assert classify_error(err(grpc.StatusCode.UNAUTHENTICATED))["category"] == "auth"
    assert (
        classify_error(err(grpc.StatusCode.PERMISSION_DENIED))["grpc_status"] == "PERMISSION_DENIED"
    )
    assert classify_error(err(grpc.StatusCode.INTERNAL))["category"] == "protocol"
