"""Mapping of core exceptions to JSON error responses."""

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from a2a_workbench.core.assistant.service import SessionNotFoundError
from a2a_workbench.core.auth.service import CredentialError
from a2a_workbench.core.blobs import BlobNotFoundError, BlobTooLargeError
from a2a_workbench.core.connection.cards import CardFetchError
from a2a_workbench.core.connection.client import InterfaceNotFoundError
from a2a_workbench.core.conversations.errors import classify_error
from a2a_workbench.core.conversations.service import ConversationNotFoundError
from a2a_workbench.core.errors import AgentCallError
from a2a_workbench.core.registry.service import AgentExistsError, AgentNotFoundError

_STATUS: dict[type[Exception], int] = {
    AgentNotFoundError: 404,
    ConversationNotFoundError: 404,
    SessionNotFoundError: 404,
    BlobNotFoundError: 404,
    AgentExistsError: 409,
    BlobTooLargeError: 413,
    InterfaceNotFoundError: 422,
    CredentialError: 422,
}


def error_response(status: int, payload: dict[str, Any]) -> JSONResponse:
    """Return ``{"error": payload}`` with the given HTTP status."""
    return JSONResponse(status_code=status, content={"error": payload})


def _handler(status: int) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    async def handle(_: Request, exc: Exception) -> JSONResponse:
        return error_response(
            status, {"category": "workbench", "message": str(exc) or type(exc).__name__}
        )

    return handle


def install_error_handlers(app: FastAPI) -> None:
    """Register JSON error responses for core exceptions on ``app``.

    Card fetch failures become 422 with the classified category of their cause.
    """

    async def card_error(_: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, CardFetchError)
        payload = classify_error(exc.cause)
        payload["message"] = str(exc)
        return error_response(422, payload)

    async def agent_call_error(_: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, AgentCallError)
        return error_response(422, exc.classified)

    app.add_exception_handler(CardFetchError, card_error)
    app.add_exception_handler(AgentCallError, agent_call_error)
    for exc_type, status in _STATUS.items():
        app.add_exception_handler(exc_type, _handler(status))
