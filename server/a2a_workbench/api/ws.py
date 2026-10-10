"""Multiplexed WebSocket delivering conversation events, exchange summaries and Assistant steps.

Client messages: ``{"op": "subscribe", "topic": ..., "after_seq": n}`` and
``{"op": "unsubscribe", "topic": ...}``. Topics are ``conversation:<id>``,
``exchanges:<id>``, ``assistant:<id>``, ``push:<agent_id>`` (deliveries) and
``health-run:<id>`` (progress of a health run).
For conversation and assistant topics, events (steps) with ``seq > after_seq``
are delivered exactly once and in order, first from storage, then live.
"""

import asyncio
import contextlib
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from a2a_workbench.core.workbench import Workbench

router = APIRouter()
TOPIC_PREFIXES = ("conversation:", "exchanges:", "assistant:", "push:", "health-run:")


async def _pump(ws: WebSocket, wb: Workbench, topic: str, after_seq: int) -> None:
    async with wb.bus.subscription(topic) as queue:
        last = after_seq
        if topic.startswith("conversation:"):
            for event in await wb.conversations.events(topic.split(":", 1)[1], after_seq):
                await ws.send_json(
                    {"topic": topic, "type": "event", "event": event.model_dump(mode="json")}
                )
                last = event.seq
        elif topic.startswith("assistant:"):
            for step in await wb.assistant.steps(topic.split(":", 1)[1], after_seq):
                await ws.send_json(
                    {"topic": topic, "type": "step", "step": step.model_dump(mode="json")}
                )
                last = step.seq
        while True:
            payload: dict[str, Any] = await queue.get()
            if payload.get("type") in ("event", "step"):
                seq = payload[payload["type"]]["seq"]
                if seq <= last:
                    continue
                last = seq
            await ws.send_json({"topic": topic, **payload})


@router.websocket("/ws")
async def websocket(ws: WebSocket) -> None:
    """Serve subscribe/unsubscribe requests until the client disconnects."""
    await ws.accept()
    wb: Workbench = ws.app.state.workbench
    pumps: dict[str, asyncio.Task[None]] = {}
    try:
        while True:
            msg = await ws.receive_json()
            op = msg.get("op") if isinstance(msg, dict) else None
            topic = msg.get("topic") if isinstance(msg, dict) else None
            if op == "subscribe" and isinstance(topic, str) and topic.startswith(TOPIC_PREFIXES):
                if topic in pumps:
                    pumps.pop(topic).cancel()
                after_seq = int(msg.get("after_seq") or 0)
                pumps[topic] = asyncio.create_task(_pump(ws, wb, topic, after_seq))
            elif op == "unsubscribe" and isinstance(topic, str) and topic in pumps:
                pumps.pop(topic).cancel()
            else:
                await ws.send_json({"type": "error", "message": f"unsupported message: {msg}"})
    except WebSocketDisconnect:
        pass
    finally:
        for task in pumps.values():
            task.cancel()
        for task in pumps.values():
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
