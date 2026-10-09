"""Webhook endpoint agents POST push notifications to."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from a2a_workbench.api.deps import get_workbench
from a2a_workbench.core.push.receiver import MAX_REQUEST
from a2a_workbench.core.workbench import Workbench

router = APIRouter()


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": {"message": message}}, status_code=status)


@router.post("/hooks/{hook_id}", include_in_schema=False)
async def receive(
    hook_id: str, request: Request, wb: Workbench = Depends(get_workbench)
) -> JSONResponse:
    if await wb.hooks.row(hook_id) is None:
        return _error(404, "unknown hook")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_REQUEST:
        return _error(413, f"notification larger than {MAX_REQUEST} bytes")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_REQUEST:
            return _error(413, f"notification larger than {MAX_REQUEST} bytes")
        chunks.append(chunk)
    status, delivery = await wb.receiver.receive(hook_id, dict(request.headers), b"".join(chunks))
    if delivery is None:
        return _error(status, "unknown hook" if status == 404 else "too many notifications")
    body = {
        "verdict": delivery.verdict,
        "reasons": delivery.reasons,
        "duplicate": delivery.duplicate,
    }
    return JSONResponse(body, status_code=status)
