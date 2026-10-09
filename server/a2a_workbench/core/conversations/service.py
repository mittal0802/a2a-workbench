"""Conversations with agents: sending messages and recording the timeline."""

import asyncio
import uuid
from collections import Counter, defaultdict
from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from typing import Any

from a2a.types import (
    CancelTaskRequest,
    GetTaskRequest,
    Message,
    Role,
    StreamResponse,
    SubscribeToTaskRequest,
)
from pydantic import BaseModel
from sqlalchemy import select

from a2a_workbench.core.a2a_json import (
    INTERRUPTED_STATES,
    TERMINAL_STATES,
    card_from_json,
    to_json,
)
from a2a_workbench.core.auth.apply import AuthPlan
from a2a_workbench.core.auth.service import AuthService
from a2a_workbench.core.blobs import BlobService
from a2a_workbench.core.bus import EventBus
from a2a_workbench.core.connection.client import open_client, select_interface
from a2a_workbench.core.connection.recorder import ExchangeSink, RecordingScope, recording_scope
from a2a_workbench.core.conversations.artifacts import ArtifactAssembler
from a2a_workbench.core.conversations.errors import classify_error
from a2a_workbench.core.conversations.gaps import analyze_recovery
from a2a_workbench.core.conversations.options import (
    SendOptions,
    build_call_context,
    build_request,
)
from a2a_workbench.core.conversations.parts import AnyPartInput, build_part
from a2a_workbench.core.conversations.timeline import TimelineEvent, event_from_stream_response
from a2a_workbench.core.faults.injector import InjectorRegistry
from a2a_workbench.core.faults.profile import FaultProfile
from a2a_workbench.core.store.db import Database
from a2a_workbench.core.store.models import (
    DEFAULT_WORKSPACE_ID,
    Agent,
    Conversation,
    TimelineEventRow,
)

DEFAULT_TITLE = "New conversation"
OPEN_STATES = frozenset({"submitted", "working"})


class ConversationNotFoundError(LookupError):
    """Raised when a conversation id does not exist."""


class ConversationOut(BaseModel):
    """A conversation and the state of its current task."""

    id: str
    agent_id: str
    title: str
    origin: str
    context_id: str | None
    task_id: str | None
    task_state: str | None
    last_seq: int
    created_at: datetime
    updated_at: datetime


def _out(c: Conversation) -> ConversationOut:
    return ConversationOut(
        id=c.id,
        agent_id=c.agent_id,
        title=c.title,
        origin=c.origin,
        context_id=c.context_id,
        task_id=c.task_id,
        task_state=c.task_state,
        last_seq=c.last_seq,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


def _event_from_row(row: TimelineEventRow) -> TimelineEvent:
    return TimelineEvent.model_validate(
        {
            "conversation_id": row.conversation_id,
            "seq": row.seq,
            "kind": row.kind,
            "ts": row.ts,
            "task_id": row.task_id,
            "context_id": row.context_id,
            "exchange_id": row.exchange_id,
            "data": row.data,
        }
    )


def _last_exchange(scope: RecordingScope) -> str | None:
    return scope.exchange_ids[-1] if scope.exchange_ids else None


class ConversationService:
    """Sends messages through the SDK and keeps an ordered, persisted timeline.

    Each emitted event gets the next per-conversation sequence number, is stored,
    and is published as ``{"type": "event", "event": ...}`` on
    ``conversation:<id>``. Sends and cancellations may overlap; sequence numbers
    stay gap-free and unique per conversation.
    """

    def __init__(
        self,
        db: Database,
        bus: EventBus,
        sink: ExchangeSink,
        blobs: BlobService,
        auth: AuthService | None = None,
    ) -> None:
        self._auth = auth
        self._db = db
        self._bus = bus
        self._sink = sink
        self._blobs = blobs
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._injectors = InjectorRegistry()
        self._open_streams: Counter[str] = Counter()

    async def create(
        self, agent_id: str, *, title: str | None = None, origin: str = "chat"
    ) -> ConversationOut:
        """Start an empty conversation with an agent."""
        conv = Conversation(
            workspace_id=DEFAULT_WORKSPACE_ID,
            agent_id=agent_id,
            title=title or DEFAULT_TITLE,
            origin=origin,
        )
        async with self._db.sessions() as session:
            session.add(conv)
            await session.commit()
        return _out(conv)

    async def for_task(
        self,
        agent_id: str,
        task_id: str,
        *,
        context_id: str | None = None,
        state: str | None = None,
    ) -> ConversationOut:
        """Return the conversation that holds ``task_id``, creating one that adopts it if none does.

        An adopting conversation starts with the given context and task state, so
        it can resubscribe to the task.
        """
        async with self._db.sessions() as session:
            row = (
                (
                    await session.execute(
                        select(Conversation)
                        .where(Conversation.agent_id == agent_id, Conversation.task_id == task_id)
                        .order_by(Conversation.updated_at.desc())
                    )
                )
                .scalars()
                .first()
            )
            if row is None:
                conv_id = (
                    (
                        await session.execute(
                            select(TimelineEventRow.conversation_id)
                            .join(Conversation, Conversation.id == TimelineEventRow.conversation_id)
                            .where(
                                Conversation.agent_id == agent_id,
                                TimelineEventRow.task_id == task_id,
                            )
                        )
                    )
                    .scalars()
                    .first()
                )
                if conv_id is not None:
                    row = await session.get(Conversation, conv_id)
            if row is not None:
                return _out(row)
            conv = Conversation(
                workspace_id=DEFAULT_WORKSPACE_ID,
                agent_id=agent_id,
                title=f"Task {task_id[:8]}",
                origin="tasks",
                context_id=context_id,
                task_id=task_id,
                task_state=state,
            )
            session.add(conv)
            await session.commit()
            return _out(conv)

    async def get(self, conversation_id: str) -> ConversationOut:
        """Return one conversation.

        Raises:
            ConversationNotFoundError: if it does not exist.
        """
        async with self._db.sessions() as session:
            conv = await session.get(Conversation, conversation_id)
        if conv is None:
            raise ConversationNotFoundError(f"conversation {conversation_id} not found")
        return _out(conv)

    async def list_for_agent(self, agent_id: str) -> list[ConversationOut]:
        """Return an agent's conversations, most recently updated first."""
        async with self._db.sessions() as session:
            rows = await session.execute(
                select(Conversation)
                .where(Conversation.agent_id == agent_id)
                .order_by(Conversation.updated_at.desc())
            )
            return [_out(c) for c in rows.scalars().all()]

    async def events(self, conversation_id: str, after_seq: int = 0) -> list[TimelineEvent]:
        """Return stored events with ``seq > after_seq`` in order."""
        async with self._db.sessions() as session:
            rows = await session.execute(
                select(TimelineEventRow)
                .where(
                    TimelineEventRow.conversation_id == conversation_id,
                    TimelineEventRow.seq > after_seq,
                )
                .order_by(TimelineEventRow.seq)
            )
            return [_event_from_row(r) for r in rows.scalars().all()]

    async def _emit(self, event: TimelineEvent) -> TimelineEvent:
        async with self._locks[event.conversation_id], self._db.sessions() as session:
            conv = await session.get(Conversation, event.conversation_id)
            if conv is None:
                raise ConversationNotFoundError(f"conversation {event.conversation_id} not found")
            conv.last_seq += 1
            event.seq = conv.last_seq
            if event.context_id and not conv.context_id:
                conv.context_id = event.context_id
            state = event.data.get("state") if event.kind in ("task", "status") else None
            if event.task_id and state:
                conv.task_id = event.task_id
                conv.task_state = state
            if event.kind == "user_message" and conv.title == DEFAULT_TITLE:
                parts = event.data["message"].get("parts", [])
                text = next((p["text"] for p in parts if p.get("text")), None)
                if text:
                    conv.title = text[:60]
            session.add(
                TimelineEventRow(
                    conversation_id=event.conversation_id,
                    seq=event.seq,
                    kind=event.kind,
                    ts=event.ts,
                    task_id=event.task_id,
                    context_id=event.context_id,
                    exchange_id=event.exchange_id,
                    data=event.data,
                )
            )
            await session.commit()
        self._bus.publish(
            f"conversation:{event.conversation_id}",
            {"type": "event", "event": event.model_dump(mode="json")},
        )
        return event

    async def _error(
        self,
        conversation_id: str,
        exc: BaseException,
        *,
        task_id: str | None = None,
        exchange_id: str | None = None,
        plan: AuthPlan | None = None,
    ) -> TimelineEvent:
        classified = classify_error(exc)
        return await self._emit(
            TimelineEvent(
                conversation_id=conversation_id,
                kind="error",
                task_id=task_id,
                exchange_id=exchange_id,
                data=plan.scrub(classified) if plan else classified,
            )
        )

    async def _failure(
        self,
        conversation_id: str,
        exc: BaseException,
        task_id: str | None,
        last_state: str | None,
        exchange_id: str | None,
        plan: AuthPlan | None = None,
    ) -> TimelineEvent:
        classified = classify_error(exc)
        if plan is not None:
            classified = plan.scrub(classified)
        open_task = last_state not in TERMINAL_STATES | INTERRUPTED_STATES
        if classified["category"] == "transport" and task_id and last_state and open_task:
            return await self._emit(
                TimelineEvent(
                    conversation_id=conversation_id,
                    kind="connection_lost",
                    task_id=task_id,
                    exchange_id=exchange_id,
                    data={**classified, "task_id": task_id, "last_state": last_state},
                )
            )
        return await self._emit(
            TimelineEvent(
                conversation_id=conversation_id,
                kind="error",
                task_id=task_id,
                exchange_id=exchange_id,
                data=classified,
            )
        )

    async def _stream_ended(
        self, conversation_id: str, task_id: str, last_state: str, exchange_id: str | None
    ) -> TimelineEvent:
        return await self._emit(
            TimelineEvent(
                conversation_id=conversation_id,
                kind="connection_lost",
                task_id=task_id,
                exchange_id=exchange_id,
                data={
                    "category": "transport",
                    "message": "The stream ended before the task finished",
                    "task_id": task_id,
                    "last_state": last_state,
                },
            )
        )

    async def _task_events(self, conversation_id: str, task_id: str) -> list[TimelineEvent]:
        return [e for e in await self.events(conversation_id) if e.task_id == task_id]

    async def resubscribe(
        self, conversation_id: str, *, faults: FaultProfile | None = None, force: bool = False
    ) -> AsyncIterator[TimelineEvent]:
        """Resubscribe to the conversation's task (SubscribeToTask) and yield its events.

        Ends with a ``recovered`` event holding the gap analysis. Refused (as an
        ``error`` event) while another stream of this conversation is open.
        Tasks already in a terminal state are refused locally unless ``force``
        is set, in which case the agent's own answer is reported.
        """
        conv, agent = await self._load(conversation_id)
        if self._open_streams[conversation_id] > 0:
            yield await self._emit(
                TimelineEvent(
                    conversation_id=conversation_id,
                    kind="error",
                    task_id=conv.task_id,
                    data={
                        "category": "workbench",
                        "message": "A live stream is already open for this conversation.",
                    },
                )
            )
            return
        if not conv.task_id or (conv.task_state in TERMINAL_STATES and not force):
            reason = (
                "There is no task to resubscribe to."
                if not conv.task_id
                else f"The task already finished ({conv.task_state})."
            )
            yield await self._emit(
                TimelineEvent(
                    conversation_id=conversation_id,
                    kind="error",
                    task_id=conv.task_id,
                    data={"category": "workbench", "message": reason},
                )
            )
            return
        task_id = conv.task_id
        before = await self._task_events(conversation_id, task_id)
        card = card_from_json(agent.card)
        assembler = ArtifactAssembler()
        after: list[TimelineEvent] = []
        state = conv.task_state
        self._open_streams[conversation_id] += 1
        with recording_scope(
            "subscribe_task", agent_id=agent.id, conversation_id=conversation_id
        ) as scope:
            plan = AuthPlan()
            try:
                plan = await self._plan(agent.id, card)
                iface = select_interface(card, agent.selected_interface_url)
                client = await open_client(
                    card,
                    iface,
                    self._sink,
                    streaming=True,
                    faults=self._injectors.get(conversation_id, faults),
                    auth=plan,
                )
                async with client:
                    async for resp in client.subscribe(
                        SubscribeToTaskRequest(id=task_id),
                        context=build_call_context(None, plan.headers),
                    ):
                        event = await self._emit(
                            event_from_stream_response(
                                resp,
                                conversation_id=conversation_id,
                                assembler=assembler,
                                exchange_id=_last_exchange(scope),
                            )
                        )
                        state = event.data.get("state", state)
                        after.append(event)
                        yield event
            except Exception as exc:
                yield await self._failure(
                    conversation_id, exc, task_id, state, _last_exchange(scope), plan=plan
                )
                return
            finally:
                self._open_streams[conversation_id] -= 1
        if state in OPEN_STATES:
            yield await self._stream_ended(conversation_id, task_id, state, _last_exchange(scope))
            return
        yield await self._emit(
            TimelineEvent(
                conversation_id=conversation_id,
                kind="recovered",
                task_id=task_id,
                exchange_id=_last_exchange(scope),
                data=analyze_recovery(before, after, "subscribe"),
            )
        )

    async def check_status(
        self, conversation_id: str, *, faults: FaultProfile | None = None
    ) -> AsyncIterator[TimelineEvent]:
        """Fetch the conversation's task (GetTask), yield it, then a ``recovered`` summary."""
        conv, agent = await self._load(conversation_id)
        if not conv.task_id:
            yield await self._emit(
                TimelineEvent(
                    conversation_id=conversation_id,
                    kind="error",
                    data={"category": "workbench", "message": "There is no task to check."},
                )
            )
            return
        task_id = conv.task_id
        before = await self._task_events(conversation_id, task_id)
        card = card_from_json(agent.card)
        with recording_scope(
            "get_task", agent_id=agent.id, conversation_id=conversation_id
        ) as scope:
            plan = AuthPlan()
            try:
                plan = await self._plan(agent.id, card)
                iface = select_interface(card, agent.selected_interface_url)
                client = await open_client(
                    card,
                    iface,
                    self._sink,
                    streaming=False,
                    faults=self._injectors.get(conversation_id, faults),
                    auth=plan,
                )
                async with client:
                    task = await client.get_task(
                        GetTaskRequest(id=task_id), context=build_call_context(None, plan.headers)
                    )
            except Exception as exc:
                yield await self._failure(
                    conversation_id, exc, task_id, conv.task_state, _last_exchange(scope), plan=plan
                )
                return
        event = await self._emit(
            event_from_stream_response(
                StreamResponse(task=task),
                conversation_id=conversation_id,
                assembler=ArtifactAssembler(),
                exchange_id=_last_exchange(scope),
            )
        )
        yield event
        yield await self._emit(
            TimelineEvent(
                conversation_id=conversation_id,
                kind="recovered",
                task_id=task_id,
                exchange_id=_last_exchange(scope),
                data=analyze_recovery(before, [event], "get_task"),
            )
        )

    async def _plan(self, agent_id: str, card: Any, skill_id: str | None = None) -> AuthPlan:
        if self._auth is None:
            return AuthPlan()
        return await self._auth.plan(agent_id, card, skill_id=skill_id)

    async def _load(self, conversation_id: str) -> tuple[Conversation, Agent]:
        async with self._db.sessions() as session:
            conv = await session.get(Conversation, conversation_id)
            if conv is None:
                raise ConversationNotFoundError(f"conversation {conversation_id} not found")
            agent = await session.get(Agent, conv.agent_id)
        if agent is None:
            raise ConversationNotFoundError(f"agent of conversation {conversation_id} is gone")
        return conv, agent

    async def send(
        self, conversation_id: str, parts: Sequence[AnyPartInput], options: SendOptions
    ) -> AsyncIterator[TimelineEvent]:
        """Send a user message and yield every resulting timeline event.

        The message continues the conversation's task when that task awaits input
        or auth; otherwise it starts a new task in the conversation's context.
        Failures are yielded as ``error`` events rather than raised.

        Raises:
            ConversationNotFoundError: if the conversation does not exist.
        """
        conv, agent = await self._load(conversation_id)
        try:
            built = [await build_part(p, self._blobs.lookup) for p in parts]
        except Exception as exc:
            yield await self._error(conversation_id, exc)
            return
        message = Message(message_id=uuid.uuid4().hex, role=Role.ROLE_USER, parts=built)
        context_id = options.context_id or conv.context_id
        if context_id:
            message.context_id = context_id
        task_id = options.task_id or (
            conv.task_id if conv.task_state in INTERRUPTED_STATES else None
        )
        if task_id:
            message.task_id = task_id
        yield await self._emit(
            TimelineEvent(
                conversation_id=conversation_id,
                kind="user_message",
                task_id=task_id,
                context_id=context_id,
                data={
                    "message": to_json(build_request(message, options).message),
                    "options": options.model_dump(mode="json"),
                },
            )
        )
        card = card_from_json(agent.card)
        assembler = ArtifactAssembler()
        with recording_scope(
            "send_message", agent_id=agent.id, conversation_id=conversation_id
        ) as scope:
            seen_task, seen_state, received = task_id, None, 0
            self._open_streams[conversation_id] += 1
            plan = AuthPlan()
            try:
                plan = await self._plan(agent.id, card, options.skill_id)
                iface = select_interface(
                    card, options.interface_url or agent.selected_interface_url
                )
                client = await open_client(
                    card,
                    iface,
                    self._sink,
                    streaming=options.stream,
                    faults=self._injectors.get(conversation_id, options.faults),
                    auth=plan,
                )
                async with client:
                    stream = client.send_message(
                        build_request(message, options),
                        context=build_call_context(options, plan.headers),
                    )
                    async for resp in stream:
                        event = await self._emit(
                            event_from_stream_response(
                                resp,
                                conversation_id=conversation_id,
                                assembler=assembler,
                                exchange_id=_last_exchange(scope),
                            )
                        )
                        seen_task = event.task_id or seen_task
                        seen_state = event.data.get("state", seen_state)
                        received += 1
                        yield event
            except Exception as exc:
                yield await self._failure(
                    conversation_id, exc, seen_task, seen_state, _last_exchange(scope), plan=plan
                )
                return
            finally:
                self._open_streams[conversation_id] -= 1
            streamed = options.stream and card.capabilities.streaming
            if received == 0:
                yield await self._emit(
                    TimelineEvent(
                        conversation_id=conversation_id,
                        kind="error",
                        task_id=task_id,
                        exchange_id=_last_exchange(scope),
                        data={
                            "category": "protocol",
                            "message": "The agent's response ended without a readable A2A event",
                        },
                    )
                )
            elif streamed and seen_task and seen_state in OPEN_STATES:
                yield await self._stream_ended(
                    conversation_id, seen_task, seen_state, _last_exchange(scope)
                )

    async def cancel(self, conversation_id: str) -> AsyncIterator[TimelineEvent]:
        """Request cancellation of the conversation's current task and yield the outcome.

        Raises:
            ConversationNotFoundError: if the conversation does not exist.
        """
        conv, agent = await self._load(conversation_id)
        if not conv.task_id or conv.task_state in TERMINAL_STATES:
            yield await self._emit(
                TimelineEvent(
                    conversation_id=conversation_id,
                    kind="error",
                    data={
                        "category": "workbench",
                        "message": "There is no running task to stop.",
                    },
                )
            )
            return
        card = card_from_json(agent.card)
        with recording_scope(
            "cancel_task", agent_id=agent.id, conversation_id=conversation_id
        ) as scope:
            plan = AuthPlan()
            try:
                plan = await self._plan(agent.id, card)
                iface = select_interface(card, agent.selected_interface_url)
                client = await open_client(card, iface, self._sink, streaming=False, auth=plan)
                async with client:
                    task = await client.cancel_task(
                        CancelTaskRequest(id=conv.task_id),
                        context=build_call_context(None, plan.headers),
                    )
                yield await self._emit(
                    event_from_stream_response(
                        StreamResponse(task=task),
                        conversation_id=conversation_id,
                        assembler=ArtifactAssembler(),
                        exchange_id=_last_exchange(scope),
                    )
                )
            except Exception as exc:
                yield await self._error(
                    conversation_id,
                    exc,
                    task_id=conv.task_id,
                    exchange_id=_last_exchange(scope),
                    plan=plan,
                )
