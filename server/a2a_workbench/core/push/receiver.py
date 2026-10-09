"""Receives and validates webhook POSTs from agents (A2A §4.3.3, §13.2)."""

import hashlib
import hmac
import json
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Any

from a2a.types import StreamResponse
from google.protobuf.json_format import MessageToDict, ParseDict, ParseError
from pydantic import BaseModel
from sqlalchemy import select

from a2a_workbench.core.a2a_json import state_name
from a2a_workbench.core.connection.recorder import REDACTED
from a2a_workbench.core.push.hooks import HookStore, digest
from a2a_workbench.core.store.db import Database
from a2a_workbench.core.store.models import PushDelivery, PushHook

TOKEN_HEADER = "x-a2a-notification-token"
"""Header the official SDK sends the config token in; A2A itself does not name one."""
RATE_LIMIT = 60
RATE_WINDOW_S = 60.0
MAX_BODY = 1024 * 1024
_KINDS = {"task", "message", "status_update", "artifact_update"}


class DeliveryOut(BaseModel):
    """One received notification and how it was judged."""

    id: str
    hook_id: str
    agent_id: str
    received_at: datetime
    verdict: str
    reasons: list[str]
    notes: list[str]
    duplicate: bool
    kind: str | None
    task_id: str | None
    state: str | None
    headers: dict[str, str]
    payload: dict[str, Any] | None


def _out(row: PushDelivery) -> DeliveryOut:
    try:
        payload = json.loads(row.body) if row.body else None
    except json.JSONDecodeError:
        payload = None
    return DeliveryOut(
        id=row.id,
        hook_id=row.hook_id,
        agent_id=row.agent_id,
        received_at=row.received_at,
        verdict=row.verdict,
        reasons=list(row.reasons or []),
        notes=list(row.notes or []),
        duplicate=row.duplicate,
        kind=row.kind,
        task_id=row.task_id,
        state=row.state,
        headers=dict(row.headers or {}),
        payload=payload if isinstance(payload, dict) else None,
    )


def _masked(headers: dict[str, str]) -> dict[str, str]:
    return {
        k: REDACTED if k in ("authorization", TOKEN_HEADER, "cookie") else v
        for k, v in headers.items()
    }


def _task_of(resp: StreamResponse, kind: str) -> tuple[str | None, str | None, str | None]:
    """Return (task id, context id, state) carried by a StreamResponse."""
    if kind == "task":
        return resp.task.id, resp.task.context_id, state_name(resp.task.status.state)
    if kind == "status_update":
        su = resp.status_update
        return su.task_id, su.context_id, state_name(su.status.state)
    if kind == "artifact_update":
        return resp.artifact_update.task_id, resp.artifact_update.context_id, None
    return resp.message.task_id or None, resp.message.context_id or None, None


class Receiver:
    """Validates deliveries to Workbench hooks, stores them and routes accepted ones.

    A delivery is accepted when its ``Authorization`` matches the hook's
    credentials (A2A §4.3.3, §13.2 MUST), its token (when sent) matches, its
    body is a ``StreamResponse`` and its task is the hook's task (§4.3.3 MUST).
    Accepted deliveries become ``push`` events in the conversation holding the
    task and are published on ``push:<agent_id>``. Repeats are acknowledged and
    flagged as duplicates without a second event. Each hook accepts at most
    ``RATE_LIMIT`` deliveries per minute.
    """

    def __init__(self, db: Database, hooks: HookStore, conversations: Any, bus: Any) -> None:
        self._db = db
        self._hooks = hooks
        self._conversations = conversations
        self._bus = bus
        self._recent: dict[str, deque[float]] = defaultdict(deque)

    def _limited(self, hook_id: str) -> bool:
        now = time.monotonic()
        window = self._recent[hook_id]
        while window and now - window[0] > RATE_WINDOW_S:
            window.popleft()
        if len(window) >= RATE_LIMIT:
            return True
        window.append(now)
        return False

    @staticmethod
    def _authentic(hook: PushHook, headers: dict[str, str]) -> bool:
        scheme, _, credentials = headers.get("authorization", "").partition(" ")
        return scheme.lower() == hook.auth_scheme.lower() and hmac.compare_digest(
            digest(credentials.strip()), hook.credentials_hash
        )

    async def receive(
        self, hook_id: str, headers: dict[str, str], body: bytes
    ) -> tuple[int, DeliveryOut | None]:
        """Judge one POST to ``/hooks/<hook_id>``; return the HTTP status and the stored delivery.

        Statuses: 200 accepted (also duplicates), 400 malformed or unexpected
        task, 401 unauthenticated or wrong token, 404 unknown hook (not
        stored), 429 rate limited (not stored).
        """
        headers = {k.lower(): v for k, v in headers.items()}
        hook = await self._hooks.row(hook_id)
        if hook is None:
            return 404, None
        if self._limited(hook_id):
            return 429, None
        text = body[:MAX_BODY].decode("utf-8", errors="replace")
        reasons: list[str] = []
        notes: list[str] = []
        if not self._authentic(hook, headers):
            reasons.append("unauthenticated")
        token = headers.get(TOKEN_HEADER)
        if token is None:
            notes.append(
                "No token received. A2A defines the config token but not how it is sent; the "
                "official SDK uses the X-A2A-Notification-Token header."
            )
        elif not hmac.compare_digest(digest(token), hook.token_hash):
            reasons.append("wrong_token")
        content_type = headers.get("content-type", "").split(";")[0].strip()
        if content_type and content_type != "application/a2a+json":
            notes.append(f"Content-Type is {content_type}; A2A §4.3.3 shows application/a2a+json.")
        kind = task_id = context_id = state = None
        payload: dict[str, Any] | None = None
        if not reasons:
            try:
                payload = json.loads(text)
                resp = ParseDict(payload, StreamResponse(), ignore_unknown_fields=False)
                kind = resp.WhichOneof("payload")
                if kind not in _KINDS:
                    raise ValueError("no payload")
                task_id, context_id, state = _task_of(resp, kind)
                payload = MessageToDict(resp)
            except (json.JSONDecodeError, ParseError, ValueError, TypeError):
                reasons.append("malformed")
        if not reasons and task_id:
            if hook.task_id is None and hook.conversation_id:
                await self._hooks.bind_task(hook.id, task_id)
                notes.append("Bound this hook to the task in its first notification.")
            elif hook.task_id is not None and task_id != hook.task_id:
                reasons.append("unexpected_task")
        body_hash = hashlib.sha256(body).hexdigest()
        duplicate = False
        if not reasons:
            async with self._db.sessions() as session:
                seen = (
                    await session.execute(
                        select(PushDelivery.id).where(
                            PushDelivery.hook_id == hook.id,
                            PushDelivery.body_hash == body_hash,
                            PushDelivery.verdict == "accepted",
                        )
                    )
                ).first()
            duplicate = seen is not None
        row = PushDelivery(
            hook_id=hook.id,
            agent_id=hook.agent_id,
            verdict="rejected" if reasons else "accepted",
            reasons=reasons,
            notes=notes,
            duplicate=duplicate,
            kind=kind,
            task_id=task_id,
            state=state,
            headers=_masked(headers),
            body=text if not ("unauthenticated" in reasons or "wrong_token" in reasons) else "",
            body_hash=body_hash,
        )
        async with self._db.sessions() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        out = _out(row)
        if reasons:
            status = 401 if {"unauthenticated", "wrong_token"} & set(reasons) else 400
            self._bus.publish(
                f"push:{hook.agent_id}",
                {"type": "delivery", "delivery": out.model_dump(mode="json")},
            )
            return status, out
        if not duplicate:
            await self._route(hook, out, payload, task_id, context_id, state, kind)
        self._bus.publish(
            f"push:{hook.agent_id}", {"type": "delivery", "delivery": out.model_dump(mode="json")}
        )
        return 200, out

    async def _route(
        self,
        hook: PushHook,
        delivery: DeliveryOut,
        payload: dict[str, Any] | None,
        task_id: str | None,
        context_id: str | None,
        state: str | None,
        kind: str | None,
    ) -> None:
        conversation_id = hook.conversation_id
        if conversation_id is None and task_id:
            conversation_id = (
                await self._conversations.for_task(hook.agent_id, task_id, context_id=context_id)
            ).id
        if conversation_id is None:
            return
        await self._conversations.record_push(
            conversation_id,
            {
                "delivery_id": delivery.id,
                "hook_id": hook.id,
                "kind": kind,
                "state": state,
                "payload": payload,
                "notes": delivery.notes,
            },
            task_id=task_id,
            context_id=context_id,
        )

    async def deliveries(self, agent_id: str, *, limit: int = 200) -> list[DeliveryOut]:
        """Return the agent's most recent deliveries, newest first."""
        async with self._db.sessions() as session:
            rows = (
                await session.execute(
                    select(PushDelivery)
                    .where(PushDelivery.agent_id == agent_id)
                    .order_by(PushDelivery.received_at.desc())
                    .limit(limit)
                )
            ).scalars()
            return [_out(r) for r in rows]

    async def delivery(self, delivery_id: str) -> DeliveryOut | None:
        """Return one delivery, or None."""
        async with self._db.sessions() as session:
            row = await session.get(PushDelivery, delivery_id)
            return _out(row) if row else None
