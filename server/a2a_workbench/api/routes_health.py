"""Health check runs and their reports."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from a2a_workbench.api.deps import get_workbench
from a2a_workbench.core.faults.profile import FaultProfile, load_profile
from a2a_workbench.core.health.model import AREAS
from a2a_workbench.core.health.runner import HealthRunOut
from a2a_workbench.core.workbench import Workbench

router = APIRouter(prefix="/api")


class RunIn(BaseModel):
    areas: list[str] | None = None
    interfaces: Literal["selected", "all"] = "selected"
    faults: str | FaultProfile | None = None


def _faults(value: str | FaultProfile | None) -> FaultProfile | None:
    if value is None or isinstance(value, FaultProfile):
        return value
    try:
        return load_profile(value)
    except ValueError as exc:
        raise HTTPException(422, detail={"category": "workbench", "message": str(exc)}) from exc


@router.get("/health/checks")
async def list_checks(wb: Workbench = Depends(get_workbench)) -> dict[str, Any]:
    return {
        "areas": AREAS,
        "checks": [
            {
                "id": c.id,
                "area": c.area,
                "title": c.title,
                "spec_ref": c.spec_ref,
                "level": c.level,
                "fix_hint": c.fix_hint,
            }
            for c in wb.health.checks
        ],
    }


@router.post("/agents/{agent_id}/health/runs", status_code=202)
async def start_run(
    agent_id: str, body: RunIn | None = None, wb: Workbench = Depends(get_workbench)
) -> dict[str, Any]:
    body = body or RunIn()
    unknown = sorted(set(body.areas or []) - set(AREAS))
    if unknown:
        raise HTTPException(
            422, detail={"category": "workbench", "message": f"unknown areas: {', '.join(unknown)}"}
        )
    run_id = await wb.health.start(
        agent_id, areas=body.areas, interfaces=body.interfaces, faults=_faults(body.faults)
    )
    return {"run_id": run_id, "topic": f"health-run:{run_id}"}


@router.get("/health/runs")
async def list_runs(
    agent_id: str | None = None, limit: int = 50, wb: Workbench = Depends(get_workbench)
) -> list[HealthRunOut]:
    return await wb.health.list(agent_id=agent_id, limit=max(1, min(limit, 500)))


@router.get("/health/runs/{run_id}")
async def get_run(run_id: str, wb: Workbench = Depends(get_workbench)) -> HealthRunOut:
    return await wb.health.get(run_id)


@router.delete("/health/runs/{run_id}/active", status_code=204)
async def stop_run(run_id: str, wb: Workbench = Depends(get_workbench)) -> Response:
    await wb.health.get(run_id)
    if not await wb.health.stop(run_id):
        raise HTTPException(
            409, detail={"category": "workbench", "message": "this run is not in progress here"}
        )
    return Response(status_code=204)


@router.get("/health/runs/{run_id}/report.json")
async def report_json(run_id: str, wb: Workbench = Depends(get_workbench)) -> Response:
    import json

    report = await wb.health.report_json(run_id)
    return Response(
        content=json.dumps(report, indent=2),
        media_type="application/json",
        headers={"content-disposition": f'attachment; filename="health-{run_id}.json"'},
    )


@router.get("/health/runs/{run_id}/report.html")
async def report_html(
    run_id: str, download: bool = False, wb: Workbench = Depends(get_workbench)
) -> HTMLResponse:
    headers = (
        {"content-disposition": f'attachment; filename="health-{run_id}.html"'} if download else {}
    )
    return HTMLResponse(await wb.health.report_html(run_id), headers=headers)
