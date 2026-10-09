"""OAuth sign-in endpoints: browser start, provider callback, implicit fragment, device polling."""

import base64
import hashlib
import json
from html import escape

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from a2a_workbench.api.deps import get_workbench
from a2a_workbench.core.a2a_json import card_from_json
from a2a_workbench.core.auth.service import BrowserStart, CredentialError, DeviceStart
from a2a_workbench.core.errors import AgentCallError
from a2a_workbench.core.workbench import Workbench

router = APIRouter()


class FlowStart(BaseModel):
    client_id: str
    client_secret: str | None = None
    scopes: list[str] = []


class BrowserStartOut(BrowserStart):
    redirect_uri: str


class ImplicitIn(BaseModel):
    state: str
    access_token: str | None = None
    expires_in: int | None = None
    scope: str | None = None
    error: str | None = None
    error_description: str | None = None


def callback_url(request: Request) -> str:
    """Return this server's OAuth redirect URI as seen by the browser."""
    return f"{str(request.base_url).rstrip('/')}/oauth/callback"


@router.post("/api/agents/{agent_id}/oauth/{scheme}/start")
async def start_browser(
    agent_id: str,
    scheme: str,
    body: FlowStart,
    request: Request,
    wb: Workbench = Depends(get_workbench),
) -> BrowserStartOut:
    agent = await wb.agents.row(agent_id)
    redirect = callback_url(request)
    start = await wb.auth.start_browser_flow(
        agent_id,
        scheme,
        client_id=body.client_id,
        client_secret=body.client_secret,
        scopes=body.scopes,
        redirect_uri=redirect,
        card=card_from_json(agent.card),
    )
    return BrowserStartOut(**start.model_dump(), redirect_uri=redirect)


@router.post("/api/agents/{agent_id}/oauth/{scheme}/device")
async def start_device(
    agent_id: str, scheme: str, body: FlowStart, wb: Workbench = Depends(get_workbench)
) -> DeviceStart:
    agent = await wb.agents.row(agent_id)
    return await wb.auth.start_device_flow(
        agent_id,
        scheme,
        client_id=body.client_id,
        client_secret=body.client_secret,
        scopes=body.scopes,
        card=card_from_json(agent.card),
    )


@router.get("/api/oauth/device/{flow_id}")
async def poll_device(flow_id: str, wb: Workbench = Depends(get_workbench)) -> dict[str, str]:
    return {"status": await wb.auth.poll_device_flow(flow_id)}


_CALLBACK_SCRIPT = (
    "try{const d=JSON.parse(document.getElementById('a2aw').textContent);"
    "window.opener&&window.opener.postMessage(d,location.origin);"
    "setTimeout(()=>window.close(),1200)}catch(e){}"
)


def _csp(*scripts: str) -> str:
    hashes = " ".join(
        "'sha256-" + base64.b64encode(hashlib.sha256(s.encode()).digest()).decode() + "'"
        for s in scripts
    )
    return (
        f"default-src 'none'; script-src {hashes}; style-src 'unsafe-inline'; "
        "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    )


def _page(title: str, message: str, status: int, ok: bool) -> HTMLResponse:
    payload = json.dumps({"type": "a2aw-oauth", "ok": ok, "message": message})
    for char, escaped in (("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e")):
        payload = payload.replace(char, escaped)
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8><title>A2A Workbench sign-in</title>"
        "<body style='font-family:Inter,system-ui,sans-serif;display:grid;place-items:center;"
        "min-height:80vh;color:#1d1d1f'><div style='text-align:center'>"
        f"<h2>{escape(title)}</h2><p>{escape(message)}</p>"
        "<p style='color:#6b6b70'>You can close this window.</p></div>"
        f"<script type=application/json id=a2aw>{payload}</script>"
        f"<script>{_CALLBACK_SCRIPT}</script></body>",
        status_code=status,
        headers={"Content-Security-Policy": _csp(_CALLBACK_SCRIPT)},
    )


IMPLICIT_SCRIPT = """
const p = Object.fromEntries(new URLSearchParams(location.hash.slice(1)));
fetch("/oauth/implicit", {method: "POST", headers: {"content-type": "application/json"},
  body: JSON.stringify(p)}).then(async r => {
  const ok = r.ok; const msg = ok ? "Signed in" : ((await r.json()).error || {}).message;
  document.getElementById("m").textContent = (ok ? "Signed in. " : "Sign-in failed: " + msg) +
    " You can close this window.";
  if (window.opener)
    window.opener.postMessage({type: "a2aw-oauth", ok, message: msg}, location.origin);
  if (ok) setTimeout(() => window.close(), 1200);
});
history.replaceState(null, "", location.pathname);
"""
IMPLICIT_PAGE = (
    "<!doctype html><meta charset=utf-8><title>A2A Workbench sign-in</title>"
    '<body style="font-family:Inter,system-ui,sans-serif;display:grid;place-items:center;'
    'min-height:80vh"><p id=m>Finishing sign-in…</p>'
    f"<script>{IMPLICIT_SCRIPT}</script></body>"
)


@router.get("/oauth/callback", include_in_schema=False)
async def oauth_callback(request: Request, wb: Workbench = Depends(get_workbench)) -> HTMLResponse:
    q = request.query_params
    if not q.get("state") and not q.get("code") and not q.get("error"):
        return HTMLResponse(
            IMPLICIT_PAGE, headers={"Content-Security-Policy": _csp(IMPLICIT_SCRIPT)}
        )
    if q.get("error"):
        message = q.get("error_description") or q["error"]
        if q.get("state"):
            try:
                await wb.auth.finish_browser_flow(
                    state=q["state"], error=q["error"], error_description=message
                )
            except (CredentialError, AgentCallError):
                pass
        return _page("Sign-in failed", message, 400, False)
    try:
        info = await wb.auth.finish_browser_flow(state=q.get("state", ""), code=q.get("code"))
    except CredentialError as exc:
        return _page("Sign-in failed", str(exc), 400, False)
    except AgentCallError as exc:
        return _page("Sign-in failed", exc.classified.get("message", "error"), 400, False)
    return _page("Signed in", f"Signed in for {info.scheme_name}.", 200, True)


@router.post("/oauth/implicit", include_in_schema=False)
async def oauth_implicit(
    body: ImplicitIn, wb: Workbench = Depends(get_workbench)
) -> dict[str, str]:
    info = await wb.auth.finish_browser_flow(
        state=body.state,
        access_token=body.access_token,
        expires_in=body.expires_in,
        scope=body.scope,
        error=body.error,
        error_description=body.error_description,
    )
    return {"status": "signed_in", "scheme": info.scheme_name}
