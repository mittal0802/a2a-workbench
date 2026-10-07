"""Conversations with agents: sending messages and recording the timeline."""

import asyncio
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator, Sequence
from datetime import datetime

from a2a.types import CancelTaskRequest, Message, Role, StreamResponse
from pydantic import BaseModel
from sqlalchemy import select

from a2a_workbench.core.a2a_json import (
    INTERRUPTED_STATES,
    TERMINAL_STATES,
    card_from_json,
    to_json,
)
from a2a_workbench.core.blobs import BlobService
from a2a_workbench.core.bus import EventBus
from a2a_workbench.core.connection.client import open_client, select_interface
from a2a_workbench.core.connection.recorder import ExchangeSink, RecordingScope, recording_scope
from a2a_workbench.core.conversations.artifacts import ArtifactAssembler
from a2a_workbench.core.conversations.errors import classify_error
from a2a_workbench.core.conversations.options import (
    SendOptions,
    build_call_context,
    build_request,
)
from a2a_workbench.core.conversations.parts import AnyPartInput, build_part
from a2a_workbench.core.conversations.timeline import TimelineEvent, event_from_stream_response
from a2a_workbench.core.store.db import Database
from a2a_workbench.core.store.models import (
    DEFAULT_WORKSPACE_ID,
    Agent,
    Conversation,
    TimelineEventRow,
)

DEFAULT_TITLE = "New conversation"


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

    def __init__(self, db: Database, bus: EventBus, sink: ExchangeSink, blobs: BlobService) -> None:
        self._db = db
        self._bus = bus
        self._sink = sink
        self._blobs = blobs
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

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
    ) -> TimelineEvent:
        return await self._emit(
            TimelineEvent(
                conversation_id=conversation_id,
                kind="error",
                task_id=task_id,
                exchange_id=exchange_id,
                data=classify_error(exc),
            )
        )

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
            try:
                iface = select_interface(
                    card, options.interface_url or agent.selected_interface_url
                )
                client = await open_client(card, iface, self._sink, streaming=options.stream)
                async with client:
                    stream = client.send_message(
                        build_request(message, options), context=build_call_context(options)
                    )
                    async for resp in stream:
                        yield await self._emit(
                            event_from_stream_response(
                                resp,
                                conversation_id=conversation_id,
                                assembler=assembler,
                                exchange_id=_last_exchange(scope),
                            )
                        )
            except Exception as exc:
                yield await self._error(
                    conversation_id, exc, task_id=task_id, exchange_id=_last_exchange(scope)
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
            try:
                iface = select_interface(card, agent.selected_interface_url)
                client = await open_client(card, iface, self._sink, streaming=False)
                async with client:
                    task = await client.cancel_task(CancelTaskRequest(id=conv.task_id))
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
                )
