"""Webhook endpoint agents POST push notifications to."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from a2a_workbench.api.deps import get_workbench
from a2a_workbench.core.workbench import Workbench

router = APIRouter()


@router.post("/hooks/{hook_id}", include_in_schema=False)
async def receive(
    hook_id: str, request: Request, wb: Workbench = Depends(get_workbench)
) -> JSONResponse:
    status, delivery = await wb.receiver.receive(
        hook_id, dict(request.headers), await request.body()
    )
    if delivery is None:
        message = "unknown hook" if status == 404 else "too many notifications"
        return JSONResponse({"error": {"message": message}}, status_code=status)
    body = {
        "verdict": delivery.verdict,
        "reasons": delivery.reasons,
        "duplicate": delivery.duplicate,
    }
    return JSONResponse(body, status_code=status)
