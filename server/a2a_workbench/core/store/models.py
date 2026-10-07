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
