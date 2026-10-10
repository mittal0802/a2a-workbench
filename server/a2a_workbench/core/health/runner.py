"""Runs checks against an agent, scores them and keeps the runs."""

import asyncio
import re
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from a2a_workbench.core.a2a_json import card_from_json
from a2a_workbench.core.connection.client import (
    interface_override,
    select_interface,
    supported,
)
from a2a_workbench.core.connection.recorder import REDACTED, recording_scope, redact_url
from a2a_workbench.core.errors import AgentCallError
from a2a_workbench.core.health.checks.common import guard
from a2a_workbench.core.health.context import PROBE_TIMEOUT_S, RunContext
from a2a_workbench.core.health.model import (
    Check,
    NotApplicable,
    Result,
    WorkbenchFailure,
    score,
    status_for,
    summarize,
)
from a2a_workbench.core.health.registry import builtin_checks
from a2a_workbench.core.store.models import HealthRun

REPORT_SCHEMA = 1
_URL = re.compile(r"(?:https?|grpc)://[^\s'\"<>]+")


def _mask(text: str, secrets: set[str]) -> str:
    """``text`` with credential values and credential-like URL parts masked."""
    if not text:
        return text
    text = _URL.sub(lambda m: redact_url(m.group(0)), text)
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    return text


def _version_of(ctx: RunContext) -> str:
    """The protocol version of the interface ``ctx`` tests (``1.0`` when unstated)."""
    for iface in ctx.card.supported_interfaces:
        if iface.url == ctx.interface_url:
            return iface.protocol_version or "1.0"
    return "1.0"


def _card_only(check: Check) -> bool:
    """Whether the check judges only the card document, whatever the interface's version."""
    return check.area == "A" and not check.id.startswith("A7")


class ProgressEvent(BaseModel):
    """A step of a run: ``started``, ``result`` (one check on one interface) or ``finished``."""

    run_id: str
    kind: Literal["started", "result", "finished"]
    data: dict[str, Any] = Field(default_factory=dict)


class HealthRunOut(BaseModel):
    """A stored run with its results."""

    id: str
    agent_id: str
    conversation_id: str | None
    status: str
    card_url: str
    areas: list[str]
    interfaces: list[str]
    score: int | None
    counts: dict[str, int]
    results: list[Result]
    started_at: datetime
    finished_at: datetime | None


class RunNotFoundError(LookupError):
    """No health run has this id."""


def _out(row: HealthRun) -> HealthRunOut:
    return HealthRunOut(
        id=row.id,
        agent_id=row.agent_id,
        conversation_id=row.conversation_id,
        status=row.status,
        card_url=row.card_url,
        areas=list(row.areas or []),
        interfaces=list(row.interfaces or []),
        score=row.score,
        counts=dict(row.counts or {}),
        results=[Result(**r) for r in row.results or []],
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


class HealthService:
    """Runs health checks against registered agents and stores the runs.

    Progress is published as ``{"type": "progress", "event": ...}`` on
    ``health-run:<id>``. Each check runs under its own recording scope, so the
    exchanges it causes become its evidence; a check that raises is recorded
    as ``error`` and the run continues.
    """

    def __init__(self, wb: Any, *, checks: list[Check] | None = None) -> None:
        self._wb = wb
        self._checks = checks
        self._running: dict[str, tuple[asyncio.Task[None], AsyncIterator[ProgressEvent]]] = {}

    async def start(
        self,
        agent_id: str,
        *,
        areas: list[str] | None = None,
        interfaces: Literal["selected", "all"] = "selected",
        faults: Any = None,
    ) -> str:
        """Start a run in the background and return its id once it is stored.

        Raises:
            AgentNotFoundError: if the agent is not registered.
        """
        events = self.run(agent_id, areas=areas, interfaces=interfaces, faults=faults)
        first = await anext(events)

        async def drain() -> None:
            try:
                async for _ in events:
                    pass
            finally:
                self._running.pop(first.run_id, None)

        self._running[first.run_id] = (asyncio.create_task(drain()), events)
        return first.run_id

    async def close(self) -> None:
        """Stop every background run (each is stored as ``stopped``)."""
        for run_id in list(self._running):
            await self.stop(run_id)

    async def recover(self) -> None:
        """Mark runs left ``running`` by an earlier process as ``stopped``."""
        async with self._wb.db.sessions() as session:
            rows = (
                await session.execute(select(HealthRun).where(HealthRun.status == "running"))
            ).scalars()
            for row in rows:
                if row.id not in self._running:
                    row.status = "stopped"
                    row.finished_at = row.finished_at or datetime.now(UTC)
            await session.commit()

    def is_running(self, run_id: str) -> bool:
        """Whether a run started with ``start`` is still in progress in this process."""
        return run_id in self._running

    async def stop(self, run_id: str) -> bool:
        """Stop a background run (stored as ``stopped``); return False if it is not running."""
        entry = self._running.pop(run_id, None)
        if entry is None:
            return False
        task, events = entry
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await events.aclose()  # type: ignore[attr-defined]
        return True

    async def findings(
        self,
        *,
        run_id: str | None = None,
        agent_id: str | None = None,
        statuses: tuple[str, ...] = ("fail", "warn", "error"),
    ) -> list[Result]:
        """Results with one of ``statuses`` from a run (default: the agent's latest run).

        Raises:
            RunNotFoundError: if the run does not exist or the agent has no runs.
        """
        if run_id is None:
            runs = await self.list(agent_id=agent_id, limit=1)
            if not runs:
                raise RunNotFoundError("no health runs yet")
            run = runs[0]
        else:
            run = await self.get(run_id)
        return [r for r in run.results if r.status in statuses]

    @property
    def checks(self) -> list[Check]:
        """The checks this service runs."""
        return self._checks if self._checks is not None else builtin_checks()

    def _interfaces(self, card: Any, agent: Any, which: str) -> list[tuple[str, str]]:
        if which == "all":
            return [(i.url, i.protocol_binding) for i in card.supported_interfaces if supported(i)]
        iface = select_interface(card, agent.selected_interface_url)
        return [(iface.url, iface.protocol_binding)]

    async def _save(self, run_id: str, **fields: Any) -> None:
        async with self._wb.db.sessions() as session:
            row = await session.get(HealthRun, run_id)
            assert row is not None
            for k, v in fields.items():
                setattr(row, k, v)
            await session.commit()

    async def run(
        self,
        agent_id: str,
        *,
        areas: list[str] | None = None,
        interfaces: Literal["selected", "all"] = "selected",
        faults: Any = None,
    ) -> AsyncIterator[ProgressEvent]:
        """Run the checks (optionally only ``areas``) and yield progress; the run is stored.

        Raises:
            AgentNotFoundError: if the agent is not registered.
        """
        agent = await self._wb.agents.get(agent_id)
        try:
            agent = await self._wb.agents.refresh_card(agent_id)
        except Exception:
            pass
        card = card_from_json(agent.card)
        try:
            secrets = (await self._wb.auth.plan(agent_id, card)).secrets()
        except Exception:
            secrets = set()
        targets = self._interfaces(card, agent, interfaces)
        checks = [c for c in self.checks if not areas or c.area in areas]
        conv = await self._wb.conversations.create(agent_id, title="Health check", origin="health")
        row = HealthRun(
            agent_id=agent_id,
            conversation_id=conv.id,
            card_url=agent.base_url.rstrip("/")
            + (agent.card_path or "/.well-known/agent-card.json"),
            areas=sorted({c.area for c in checks}),
            interfaces=[url for url, _ in targets],
        )
        async with self._wb.db.sessions() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        run_id = row.id
        topic = f"health-run:{run_id}"

        def emit(event: ProgressEvent) -> ProgressEvent:
            self._wb.bus.publish(
                topic, {"type": "progress", "event": event.model_dump(mode="json")}
            )
            return event

        results: list[Result] = []
        contexts = {
            url: RunContext(
                self._wb,
                agent,
                card,
                interface_url=url,
                binding=binding,
                conversation_id=conv.id,
                faults=faults,
            )
            for url, binding in targets
        }
        try:
            yield emit(
                ProgressEvent(
                    run_id=run_id,
                    kind="started",
                    data={"checks": len(checks), "interfaces": [url for url, _ in targets]},
                )
            )
            for check in checks:
                for url, _binding in targets if check.per_interface else targets[:1]:
                    result = await self._run_one(check, contexts[url], agent_id, conv.id, secrets)
                    if not check.per_interface:
                        result.interface = None
                    results.append(result)
                    await self._save(run_id, results=[r.model_dump(mode="json") for r in results])
                    yield emit(
                        ProgressEvent(
                            run_id=run_id, kind="result", data=result.model_dump(mode="json")
                        )
                    )
        finally:
            counts = summarize(results)
            await self._save(
                run_id,
                results=[r.model_dump(mode="json") for r in results],
                counts=counts,
                score=score(counts),
                status="done"
                if len(results) == sum(len(targets) if c.per_interface else 1 for c in checks)
                else "stopped",
                finished_at=datetime.now(UTC),
            )
        yield emit(
            ProgressEvent(
                run_id=run_id, kind="finished", data={"score": score(counts), "counts": counts}
            )
        )

    async def _run_one(
        self, check: Check, ctx: RunContext, agent_id: str, conv_id: str, secrets: set[str]
    ) -> Result:
        result = await self._judge(check, ctx, agent_id, conv_id)
        result.expected = _mask(result.expected, secrets)
        result.actual = _mask(result.actual, secrets)
        return result

    async def _judge(self, check: Check, ctx: RunContext, agent_id: str, conv_id: str) -> Result:
        started = time.monotonic()
        token = interface_override.set(ctx.interface_url)
        base = {
            "check_id": check.id,
            "area": check.area,
            "title": check.title,
            "spec_ref": check.spec_ref,
            "level": check.level,
            "interface": ctx.interface_url,
            "fix_hint": check.fix_hint,
        }
        try:
            with recording_scope(
                f"health:{check.id}", agent_id=agent_id, conversation_id=conv_id
            ) as scope:
                try:
                    version = _version_of(ctx)
                    if version.startswith("0.") and not _card_only(check):
                        return Result(
                            **base,
                            status="not_supported",
                            actual=f"the checks cite A2A 1.0; this interface speaks A2A {version}",
                        )
                    reason = check.applies(ctx)
                    if reason:
                        return Result(**base, status="not_supported", actual=reason)
                    outcome = await asyncio.wait_for(check.run(ctx), PROBE_TIMEOUT_S)
                    status = status_for(check, outcome)
                    return Result(
                        **base,
                        status=status,
                        expected=outcome.expected,
                        actual=outcome.actual,
                        exchange_ids=list(scope.exchange_ids),
                        duration_ms=round((time.monotonic() - started) * 1000, 1),
                    )
                except AgentCallError as exc:
                    try:
                        guard(exc.classified)
                        actual = f"AgentCallError: {exc}"[:500]
                    except NotApplicable as na:
                        return Result(**base, status="not_supported", actual=str(na))
                    except WorkbenchFailure as wf:
                        actual = f"WorkbenchFailure: {wf}"[:500]
                except NotApplicable as exc:
                    return Result(
                        **base,
                        status="not_supported",
                        actual=str(exc),
                        exchange_ids=list(scope.exchange_ids),
                        duration_ms=round((time.monotonic() - started) * 1000, 1),
                    )
                except TimeoutError:
                    actual = f"the probe did not finish within {PROBE_TIMEOUT_S:g} s"
                except Exception as exc:
                    actual = f"{type(exc).__name__}: {exc}"[:500]
                return Result(
                    **base,
                    status="error",
                    actual=actual,
                    exchange_ids=list(scope.exchange_ids),
                    duration_ms=round((time.monotonic() - started) * 1000, 1),
                )
        finally:
            interface_override.reset(token)

    async def get(self, run_id: str) -> HealthRunOut:
        """Return a stored run.

        Raises:
            RunNotFoundError: if it does not exist.
        """
        async with self._wb.db.sessions() as session:
            row = await session.get(HealthRun, run_id)
        if row is None:
            raise RunNotFoundError(f"health run {run_id} not found")
        return _out(row)

    async def list(self, *, agent_id: str | None = None, limit: int = 50) -> list[HealthRunOut]:
        """Return runs, newest first (optionally for one agent)."""
        query = select(HealthRun).order_by(HealthRun.started_at.desc()).limit(limit)
        if agent_id:
            query = query.where(HealthRun.agent_id == agent_id)
        async with self._wb.db.sessions() as session:
            return [_out(r) for r in (await session.execute(query)).scalars()]

    async def report_json(self, run_id: str) -> dict[str, Any]:
        """Return the run as a versioned report (schema ``REPORT_SCHEMA``)."""
        run = await self.get(run_id)
        agent = await self._wb.agents.get(run.agent_id)
        return {
            "schema": REPORT_SCHEMA,
            "run_id": run.id,
            "agent": {"id": agent.id, "name": agent.name},
            "card_url": run.card_url,
            "interfaces": run.interfaces,
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "score": run.score,
            "counts": run.counts,
            "results": [r.model_dump(mode="json") for r in run.results],
        }

    async def report_html(self, run_id: str) -> str:
        """Return the run as a self-contained HTML page."""
        from a2a_workbench.core.health.report import render_html

        return render_html(await self.report_json(run_id))
