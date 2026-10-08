"""MCP tools for testing A2A agents with A2A Workbench.

Every tool returns JSON. Failures are returned as ``{"error": {"category",
"message", ...}}`` (categories: transport, auth, protocol, workbench) instead of
being raised, so an agent can read and act on them.
"""

from datetime import datetime
from typing import Any

from mcp.server.mcpserver import MCPServer

from a2a_workbench.core.connection.cards import CardFetchError
from a2a_workbench.core.conversations.errors import classify_error
from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.conversations.parts import (
    AnyPartInput,
    DataPartInput,
    FilePartInput,
    TextPartInput,
)
from a2a_workbench.core.errors import AgentCallError
from a2a_workbench.core.faults.profile import PRESETS, FaultProfile, load_profile
from a2a_workbench.core.registry.service import AgentNotFoundError, AgentOut
from a2a_workbench.core.tasks.service import ListTasksFilter
from a2a_workbench.core.workbench import Workbench

INSTRUCTIONS = """\
A2A Workbench tests A2A (Agent2Agent protocol) agents through the official SDK.
Typical flow: fetch_card(url) -> send_message(agent=url, text=...) -> read
events and final_state -> list_exchanges(conversation_id) / get_exchange(id) to
see exact wire traffic. Use faults="flaky_stream" (see fault_presets) to drop
a stream, then resubscribe(conversation_id) and read the "recovered" event's
gap analysis. Errors come back as {"error": {...}} with a category.
"""


def _error(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, AgentCallError):
        return {"error": exc.classified}
    if isinstance(exc, CardFetchError):
        return {"error": {**classify_error(exc.cause), "message": str(exc)}}
    if isinstance(exc, ValueError | LookupError):
        return {"error": {"category": "workbench", "message": str(exc)}}
    return {"error": classify_error(exc)}


def _faults(spec: str | dict[str, Any] | None) -> FaultProfile | None:
    if spec is None:
        return None
    if isinstance(spec, dict):
        return FaultProfile.model_validate(spec)
    return load_profile(spec)


def _events(events: list[Any]) -> list[dict[str, Any]]:
    return [e.model_dump(mode="json") for e in events]


def _final_state(events: list[dict[str, Any]]) -> str | None:
    for e in reversed(events):
        if e["kind"] in ("task", "status") and e["data"].get("state"):
            return str(e["data"]["state"])
        if e["kind"] == "message":
            return "message"
    return None


def _last_error(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    last = events[-1] if events else None
    if last and last["kind"] in ("error", "connection_lost"):
        return dict(last["data"])
    return None


def build_mcp_server(wb: Workbench) -> MCPServer:
    """Return an MCP server whose tools operate on ``wb``."""
    server = MCPServer("a2a-workbench", instructions=INSTRUCTIONS)

    async def resolve(agent: str) -> AgentOut:
        try:
            return await wb.agents.resolve(agent)
        except AgentNotFoundError:
            return await wb.agents.add(agent)

    @server.tool()
    async def list_agents() -> dict[str, Any]:
        """List registered agents (id, name, base_url, selected interface, interfaces)."""
        agents = [
            {
                "id": a.id,
                "name": a.name,
                "base_url": a.base_url,
                "selected_interface_url": a.selected_interface_url,
                "interfaces": [i.model_dump() for i in a.interfaces],
                "signature_status": a.signature_status,
            }
            for a in await wb.agents.list()
        ]
        return {"agents": agents}

    @server.tool()
    async def add_agent(url: str) -> dict[str, Any]:
        """Register the A2A agent at url (base URL or agent card URL) and return it."""
        try:
            return (await wb.agents.add(url)).model_dump(mode="json")
        except Exception as exc:
            return _error(exc)

    @server.tool()
    async def fetch_card(target: str, extended: bool = False) -> dict[str, Any]:
        """Fetch and verify an agent card. target is a URL or a registered agent.

        With extended=true, call GetExtendedAgentCard and return the card plus
        its differences from the public card.
        """
        try:
            if extended:
                try:
                    agent = await wb.agents.resolve(target)
                    return (await wb.agents.get_extended_card(agent.id)).model_dump(mode="json")
                except AgentNotFoundError:
                    out = await wb.agents.extended_card_for_url(target)
                    return out.model_dump(mode="json")
            return (await wb.agents.preview(target)).model_dump(mode="json")
        except Exception as exc:
            return _error(exc)

    @server.tool()
    async def send_message(
        agent: str,
        text: str,
        data: Any = None,
        file_urls: list[str] | None = None,
        stream: bool = True,
        return_immediately: bool = False,
        accepted_output_modes: list[str] | None = None,
        history_length: int | None = None,
        extensions: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        conversation_id: str | None = None,
        faults: str | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a message to an agent (URL, id or name) and wait for the reply.

        Pass conversation_id from a previous result to continue that
        conversation (it answers an input_required question automatically).
        faults is a preset name (see fault_presets) or a profile object.
        Returns conversation_id, every timeline event, final_state and error.
        """
        try:
            target = await resolve(agent)
            profile = _faults(faults)
            conv_id = conversation_id or (await wb.conversations.create(target.id, origin="mcp")).id
        except Exception as exc:
            return _error(exc)
        parts: list[AnyPartInput] = [TextPartInput(text=text)]
        parts += [FilePartInput(url=u) for u in file_urls or []]
        if data is not None:
            parts.append(DataPartInput(data=data))
        options = SendOptions(
            stream=stream,
            return_immediately=return_immediately,
            accepted_output_modes=accepted_output_modes or [],
            history_length=history_length,
            extensions=extensions or [],
            message_metadata=metadata,
            faults=profile,
        )
        events = _events([e async for e in wb.conversations.send(conv_id, parts, options)])
        return {
            "conversation_id": conv_id,
            "events": events,
            "final_state": _final_state(events),
            "error": _last_error(events),
        }

    @server.tool()
    async def get_task(
        agent: str, task_id: str, history_length: int | None = None
    ) -> dict[str, Any]:
        """Get a task (GetTask) from an agent."""
        try:
            return await wb.tasks.get(
                (await resolve(agent)).id, task_id, history_length=history_length
            )
        except Exception as exc:
            return _error(exc)

    @server.tool()
    async def list_tasks(
        agent: str,
        context_id: str | None = None,
        status: str | None = None,
        status_timestamp_after: str | None = None,
        include_artifacts: bool | None = None,
        history_length: int | None = None,
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """List an agent's tasks (ListTasks) with any filter; follow next_page_token to page."""
        try:
            f = ListTasksFilter(
                context_id=context_id,
                status=status,
                status_timestamp_after=(
                    datetime.fromisoformat(status_timestamp_after)
                    if status_timestamp_after
                    else None
                ),
                include_artifacts=include_artifacts,
                history_length=history_length,
                page_size=page_size,
                page_token=page_token,
            )
            return await wb.tasks.list((await resolve(agent)).id, f)
        except Exception as exc:
            return _error(exc)

    @server.tool()
    async def cancel_task(agent: str, task_id: str) -> dict[str, Any]:
        """Cancel a task (CancelTask)."""
        try:
            return await wb.tasks.cancel((await resolve(agent)).id, task_id)
        except Exception as exc:
            return _error(exc)

    @server.tool()
    async def subscribe_task(agent: str, task_id: str) -> dict[str, Any]:
        """Resubscribe to a running task (SubscribeToTask); return its events until it ends."""
        try:
            agent_id = (await resolve(agent)).id
            return {"events": [e async for e in wb.tasks.subscribe(agent_id, task_id)]}
        except Exception as exc:
            return _error(exc)

    @server.tool()
    async def resubscribe(conversation_id: str, force: bool = False) -> dict[str, Any]:
        """Resubscribe to a conversation's task after a lost connection.

        The last event is "recovered" with a gap analysis: snapshot_first,
        missed_states, missed_artifacts, duplicate_events, state_after.
        """
        try:
            events = [e async for e in wb.conversations.resubscribe(conversation_id, force=force)]
        except Exception as exc:
            return _error(exc)
        return {"events": _events(events)}

    @server.tool()
    async def check_status(conversation_id: str) -> dict[str, Any]:
        """Fetch a conversation's task with GetTask and report what was missed."""
        try:
            events = [e async for e in wb.conversations.check_status(conversation_id)]
        except Exception as exc:
            return _error(exc)
        return {"events": _events(events)}

    @server.tool()
    async def list_exchanges(conversation_id: str) -> dict[str, Any]:
        """List every HTTP/gRPC exchange of a conversation (summaries, oldest first)."""
        return {"exchanges": await wb.exchanges.list(conversation_id=conversation_id)}

    @server.tool()
    async def get_exchange(exchange_id: str) -> dict[str, Any]:
        """Return one exchange with headers (secrets redacted), bodies, frames, timing, fault."""
        record = await wb.exchanges.get(exchange_id)
        return record or {"error": {"category": "workbench", "message": "exchange not found"}}

    @server.tool()
    async def fault_presets() -> dict[str, Any]:
        """List the built-in network fault presets usable as send_message(faults=...)."""
        return {"presets": [p.model_dump(mode="json") for p in PRESETS.values()]}

    return server
