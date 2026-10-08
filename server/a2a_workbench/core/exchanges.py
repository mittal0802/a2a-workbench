"""Persistence and live publication of recorded exchanges."""

from typing import Any

from sqlalchemy import select

from a2a_workbench.core.bus import EventBus
from a2a_workbench.core.connection.recorder import Exchange
from a2a_workbench.core.store.db import Database
from a2a_workbench.core.store.models import ExchangeRow

_SUMMARY_KEYS = (
    "id",
    "operation",
    "http_method",
    "url",
    "started_at",
    "status",
    "duration_ms",
    "error",
    "agent_id",
    "conversation_id",
    "complete",
)


def summarize(record: dict[str, Any]) -> dict[str, Any]:
    """Return the list-view fields of an exchange record, plus its frame count."""
    summary = {k: record.get(k) for k in _SUMMARY_KEYS}
    summary["frame_count"] = len(record.get("frames") or [])
    return summary


class ExchangeStore:
    """Stores exchanges and announces each one on ``exchanges:<conversation_id>``."""

    def __init__(self, db: Database, bus: EventBus) -> None:
        self._db = db
        self._bus = bus

    async def __call__(self, exchange: Exchange) -> None:
        """Persist ``exchange``, replacing any earlier record of it, and publish its summary."""
        record = exchange.to_record()
        async with self._db.sessions() as session:
            await session.merge(
                ExchangeRow(
                    id=exchange.id,
                    agent_id=exchange.agent_id,
                    conversation_id=exchange.conversation_id,
                    operation=exchange.operation,
                    started_at=exchange.started_at,
                    duration_ms=exchange.duration_ms,
                    status=exchange.status,
                    error=exchange.error,
                    record=record,
                )
            )
            await session.commit()
        if exchange.conversation_id:
            self._bus.publish(
                f"exchanges:{exchange.conversation_id}",
                {"type": "exchange", "exchange": summarize(record)},
            )

    async def get(self, exchange_id: str) -> dict[str, Any] | None:
        """Return the full record of one exchange, or None."""
        async with self._db.sessions() as session:
            row = await session.get(ExchangeRow, exchange_id)
            return row.record if row else None

    async def list(
        self,
        *,
        conversation_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return up to ``limit`` most recent exchange summaries, oldest first."""
        query = select(ExchangeRow).order_by(ExchangeRow.started_at.desc()).limit(limit)
        if conversation_id:
            query = query.where(ExchangeRow.conversation_id == conversation_id)
        if agent_id:
            query = query.where(ExchangeRow.agent_id == agent_id)
        async with self._db.sessions() as session:
            rows = (await session.execute(query)).scalars().all()
        return [summarize(r.record) for r in reversed(rows)]
