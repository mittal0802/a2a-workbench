"""Health, blob and exchange endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile

from a2a_workbench import __version__
from a2a_workbench.api.deps import get_workbench
from a2a_workbench.core.blobs import BlobNotFoundError, BlobOut
from a2a_workbench.core.faults.profile import PRESETS, FaultProfile
from a2a_workbench.core.workbench import Workbench

router = APIRouter(prefix="/api")


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/fault-presets")
async def fault_presets() -> list[FaultProfile]:
    return list(PRESETS.values())


@router.post("/blobs", status_code=201)
async def upload_blob(file: UploadFile, wb: Workbench = Depends(get_workbench)) -> BlobOut:
    data = await file.read(wb.blobs.max_bytes + 1)
    return await wb.blobs.put(data, file.content_type or "", file.filename)


@router.get("/blobs/{blob_id}")
async def download_blob(blob_id: str, wb: Workbench = Depends(get_workbench)) -> Response:
    blob = await wb.blobs.get(blob_id)
    if blob is None:
        raise BlobNotFoundError(f"uploaded file {blob_id} not found")
    headers = (
        {"content-disposition": f'inline; filename="{blob.filename}"'} if blob.filename else {}
    )
    return Response(content=blob.data, media_type=blob.media_type, headers=headers)


@router.get("/exchanges")
async def list_exchanges(
    conversation_id: str | None = None,
    agent_id: str | None = None,
    limit: int = 200,
    wb: Workbench = Depends(get_workbench),
) -> list[dict[str, Any]]:
    return await wb.exchanges.list(
        conversation_id=conversation_id, agent_id=agent_id, limit=max(1, min(limit, 1000))
    )


@router.get("/exchanges/{exchange_id}")
async def get_exchange(exchange_id: str, wb: Workbench = Depends(get_workbench)) -> dict[str, Any]:
    record = await wb.exchanges.get(exchange_id)
    if record is None:
        raise HTTPException(404, detail="exchange not found")
    return record
