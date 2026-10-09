"""Relational schema of the Workbench state."""

import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DEFAULT_WORKSPACE_ID = "default"


def new_id() -> str:
    """Return a random 32-character hexadecimal identifier."""
    return uuid.uuid4().hex


def utcnow() -> datetime:
    """Return the current time as an aware UTC datetime."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base mapping ``dict``/``list`` annotations to JSON columns."""

    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSON, list[Any]: JSON}


class Workspace(Base):
    __tablename__ = "workspace"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))


class Agent(Base):
    __tablename__ = "agent"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    base_url: Mapped[str] = mapped_column(String(2000))
    card_path: Mapped[str | None] = mapped_column(String(500), default=None)
    card: Mapped[dict[str, Any]]
    extended_card: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    signature_status: Mapped[str] = mapped_column(String(20))
    signature_detail: Mapped[str | None] = mapped_column(String(1000), default=None)
    selected_interface_url: Mapped[str | None] = mapped_column(String(2000), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Conversation(Base):
    __tablename__ = "conversation"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agent.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    origin: Mapped[str] = mapped_column(String(20), default="chat")
    context_id: Mapped[str | None] = mapped_column(String(200), default=None)
    task_id: Mapped[str | None] = mapped_column(String(200), default=None)
    task_state: Mapped[str | None] = mapped_column(String(30), default=None)
    last_seq: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TimelineEventRow(Base):
    __tablename__ = "timeline_event"
    __table_args__ = (UniqueConstraint("conversation_id", "seq"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversation.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    task_id: Mapped[str | None] = mapped_column(String(200), default=None)
    context_id: Mapped[str | None] = mapped_column(String(200), default=None)
    exchange_id: Mapped[str | None] = mapped_column(String(32), default=None)
    data: Mapped[dict[str, Any]]


class ExchangeRow(Base):
    __tablename__ = "exchange"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(32), index=True, default=DEFAULT_WORKSPACE_ID)
    agent_id: Mapped[str | None] = mapped_column(String(32), index=True, default=None)
    conversation_id: Mapped[str | None] = mapped_column(String(32), index=True, default=None)
    operation: Mapped[str] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[float | None] = mapped_column(Float, default=None)
    status: Mapped[int | None] = mapped_column(Integer, default=None)
    error: Mapped[str | None] = mapped_column(String(2000), default=None)
    record: Mapped[dict[str, Any]]


class Blob(Base):
    __tablename__ = "blob"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(32), index=True, default=DEFAULT_WORKSPACE_ID)
    media_type: Mapped[str] = mapped_column(String(200))
    filename: Mapped[str | None] = mapped_column(String(500), default=None)
    size: Mapped[int] = mapped_column(Integer)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Credential(Base):
    __tablename__ = "credential"
    __table_args__ = (UniqueConstraint("agent_id", "scheme_name"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    scheme_name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(30))
    encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ProviderKey(Base):
    __tablename__ = "provider_key"
    provider: Mapped[str] = mapped_column(String(30), primary_key=True)
    encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    base_url: Mapped[str | None] = mapped_column(String(500), default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AssistantSession(Base):
    __tablename__ = "assistant_session"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="New chat")
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(200))
    response_mode: Mapped[str] = mapped_column(String(20), default="rewrite")
    agent_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    limits: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="idle")
    transcript: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    ids: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    contexts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    pending: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    budget: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    last_seq: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AssistantStepRow(Base):
    __tablename__ = "assistant_step"
    __table_args__ = (UniqueConstraint("session_id", "seq"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("assistant_session.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PushHook(Base):
    __tablename__ = "push_hook"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(32), default=None)
    task_id: Mapped[str | None] = mapped_column(String(200), index=True, default=None)
    url: Mapped[str | None] = mapped_column(String(2000), default=None)
    auth_scheme: Mapped[str] = mapped_column(String(30), default="Bearer")
    credentials_hash: Mapped[str] = mapped_column(String(64))
    token_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PushDelivery(Base):
    __tablename__ = "push_delivery"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    hook_id: Mapped[str] = mapped_column(String(32), index=True)
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    verdict: Mapped[str] = mapped_column(String(20))
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes: Mapped[list[str]] = mapped_column(JSON, default=list)
    duplicate: Mapped[bool] = mapped_column(default=False)
    kind: Mapped[str | None] = mapped_column(String(30), default=None)
    task_id: Mapped[str | None] = mapped_column(String(200), default=None)
    state: Mapped[str | None] = mapped_column(String(30), default=None)
    headers: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    body: Mapped[str] = mapped_column(Text, default="")
    body_hash: Mapped[str] = mapped_column(String(64), index=True)


class WorkbenchSetting(Base):
    __tablename__ = "workbench_setting"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(2000))
