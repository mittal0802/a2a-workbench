"""Registered agents."""

from datetime import datetime
from typing import Any

from a2a.types import AgentCard
from pydantic import BaseModel
from sqlalchemy import delete, select

from a2a_workbench.core.a2a_json import card_from_json
from a2a_workbench.core.connection.cards import SignatureStatus, fetch_card, split_card_url
from a2a_workbench.core.connection.client import SUPPORTED_BINDINGS, select_interface
from a2a_workbench.core.connection.recorder import ExchangeSink
from a2a_workbench.core.store.db import Database
from a2a_workbench.core.store.models import (
    DEFAULT_WORKSPACE_ID,
    Agent,
    Conversation,
    ExchangeRow,
    TimelineEventRow,
)


class AgentNotFoundError(LookupError):
    """Raised when no agent matches an id or reference."""


class AgentExistsError(ValueError):
    """Raised when an agent with the same base URL and card path is registered."""


class InterfaceOut(BaseModel):
    """One interface of an agent card."""

    url: str
    binding: str
    protocol_version: str
    tenant: str
    supported: bool


class AgentOut(BaseModel):
    """A registered agent."""

    id: str
    name: str
    base_url: str
    card_path: str | None
    card: dict[str, Any]
    signature_status: str
    signature_detail: str | None
    selected_interface_url: str | None
    interfaces: list[InterfaceOut]
    created_at: datetime
    updated_at: datetime


class CardPreview(BaseModel):
    """A fetched card that has not been registered."""

    card: dict[str, Any]
    signature_status: SignatureStatus
    signature_detail: str | None
    interfaces: list[InterfaceOut]
    default_interface_url: str | None
    exchange_ids: list[str]


def interfaces_of(card: AgentCard) -> list[InterfaceOut]:
    """Return the card's interfaces, flagging those whose binding this build supports."""
    return [
        InterfaceOut(
            url=i.url,
            binding=i.protocol_binding,
            protocol_version=i.protocol_version,
            tenant=i.tenant,
            supported=i.protocol_binding in SUPPORTED_BINDINGS,
        )
        for i in card.supported_interfaces
    ]


def default_interface_url(card: AgentCard) -> str | None:
    """Return the preferred supported interface URL of ``card``, or None if none is usable."""
    supported = [i for i in card.supported_interfaces if i.protocol_binding in SUPPORTED_BINDINGS]
    if not supported:
        return None
    return select_interface(AgentCard(supported_interfaces=supported), None).url


def _out(agent: Agent) -> AgentOut:
    return AgentOut(
        id=agent.id,
        name=agent.name,
        base_url=agent.base_url,
        card_path=agent.card_path,
        card=agent.card,
        signature_status=agent.signature_status,
        signature_detail=agent.signature_detail,
        selected_interface_url=agent.selected_interface_url,
        interfaces=interfaces_of(card_from_json(agent.card)),
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


class AgentService:
    """Registers agents by URL and keeps their cards."""

    def __init__(self, db: Database, sink: ExchangeSink) -> None:
        self._db = db
        self._sink = sink

    async def preview(self, url: str) -> CardPreview:
        """Fetch and verify the card at ``url`` without registering it.

        Raises:
            CardFetchError: if the card cannot be loaded.
        """
        result = await fetch_card(url, self._sink)
        return CardPreview(
            card=result.card_json,
            signature_status=result.signature_status,
            signature_detail=result.signature_detail,
            interfaces=interfaces_of(result.card),
            default_interface_url=default_interface_url(result.card),
            exchange_ids=result.exchange_ids,
        )

    async def add(self, url: str, card_path: str | None = None) -> AgentOut:
        """Fetch the card at ``url`` and register the agent.

        Raises:
            AgentExistsError: if the same base URL and card path is registered.
            CardFetchError: if the card cannot be loaded.
        """
        base_url, derived_path = split_card_url(url)
        path = card_path or derived_path
        async with self._db.sessions() as session:
            query = select(Agent).where(Agent.base_url == base_url)
            query = query.where(
                Agent.card_path.is_(None) if path is None else Agent.card_path == path
            )
            if (await session.execute(query)).scalar_one_or_none() is not None:
                raise AgentExistsError(f"{url.strip()} is already registered")
        result = await fetch_card(url, self._sink, card_path=card_path)
        agent = Agent(
            workspace_id=DEFAULT_WORKSPACE_ID,
            name=result.card.name or base_url,
            base_url=base_url,
            card_path=path,
            card=result.card_json,
            signature_status=result.signature_status,
            signature_detail=result.signature_detail,
            selected_interface_url=default_interface_url(result.card),
        )
        async with self._db.sessions() as session:
            session.add(agent)
            await session.commit()
        return _out(agent)

    async def list(self) -> list[AgentOut]:
        """Return all agents, oldest first."""
        async with self._db.sessions() as session:
            rows = (await session.execute(select(Agent).order_by(Agent.created_at))).scalars()
            return [_out(a) for a in rows.all()]

    async def row(self, agent_id: str) -> Agent:
        """Return the stored agent row.

        Raises:
            AgentNotFoundError: if it does not exist.
        """
        async with self._db.sessions() as session:
            agent = await session.get(Agent, agent_id)
        if agent is None:
            raise AgentNotFoundError(f"agent {agent_id} not found")
        return agent

    async def get(self, agent_id: str) -> AgentOut:
        """Return one agent.

        Raises:
            AgentNotFoundError: if it does not exist.
        """
        return _out(await self.row(agent_id))

    async def resolve(self, ref: str) -> AgentOut:
        """Return the agent whose id, name or base URL equals ``ref``.

        Raises:
            AgentNotFoundError: if none matches.
        """
        base_url, _ = split_card_url(ref)
        for agent in await self.list():
            if ref in (agent.id, agent.name) or agent.base_url == base_url:
                return agent
        raise AgentNotFoundError(f"no agent matches {ref}")

    async def remove(self, agent_id: str) -> None:
        """Delete an agent with its conversations, events and exchanges.

        Raises:
            AgentNotFoundError: if it does not exist.
        """
        await self.row(agent_id)
        async with self._db.sessions() as session:
            conv_ids = select(Conversation.id).where(Conversation.agent_id == agent_id)
            await session.execute(
                delete(TimelineEventRow).where(TimelineEventRow.conversation_id.in_(conv_ids))
            )
            await session.execute(delete(Conversation).where(Conversation.agent_id == agent_id))
            await session.execute(delete(ExchangeRow).where(ExchangeRow.agent_id == agent_id))
            await session.execute(delete(Agent).where(Agent.id == agent_id))
            await session.commit()

    async def refresh_card(self, agent_id: str) -> AgentOut:
        """Re-fetch the agent's card, keeping the selected interface while still listed.

        Raises:
            AgentNotFoundError: if it does not exist.
            CardFetchError: if the card cannot be loaded.
        """
        agent = await self.row(agent_id)
        result = await fetch_card(
            agent.base_url, self._sink, card_path=agent.card_path, agent_id=agent_id
        )
        urls = {i.url for i in result.card.supported_interfaces}
        async with self._db.sessions() as session:
            row = await session.get(Agent, agent_id)
            if row is None:
                raise AgentNotFoundError(f"agent {agent_id} not found")
            row.card = result.card_json
            row.name = result.card.name or row.name
            row.signature_status = result.signature_status
            row.signature_detail = result.signature_detail
            if row.selected_interface_url not in urls:
                row.selected_interface_url = default_interface_url(result.card)
            await session.commit()
            return _out(row)

    async def set_interface(self, agent_id: str, url: str) -> AgentOut:
        """Select the interface used for future calls.

        Raises:
            AgentNotFoundError: if the agent does not exist.
            InterfaceNotFoundError: if the card has no interface at ``url``.
        """
        agent = await self.row(agent_id)
        select_interface(card_from_json(agent.card), url)
        async with self._db.sessions() as session:
            row = await session.get(Agent, agent_id)
            if row is None:
                raise AgentNotFoundError(f"agent {agent_id} not found")
            row.selected_interface_url = url
            await session.commit()
            return _out(row)
