"""MCP tools for testing A2A agents with A2A Workbench.

Every tool returns JSON. Failures are returned as ``{"error": {"category",
"message", ...}}`` (categories: transport, auth, protocol, workbench) instead of
being raised, so an agent can read and act on them.
"""

import asyncio
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
gap analysis. An "auth" error means the agent needs sign-in: auth_status(agent)
lists its schemes, then set_credential or sign_in; auth_probe checks the agent
really enforces what it declares. assist(goal, agents) runs an orchestrator
LLM that calls agents the way the A2A spec defines a client agent; its steps
show every call and rejected call. Errors come back as {"error": {...}} with a
category.
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
        timeout_s: float = 120,
        skill_id: str | None = None,
    ) -> dict[str, Any]:
        """Send a message to an agent (URL, id or name) and wait for the reply.

        Pass conversation_id from a previous result to continue that
        conversation (it answers an input_required question automatically).
        faults is a preset name (see fault_presets) or a profile object.
        skill_id applies that skill's security requirements from the card when
        choosing credentials; it is not sent (A2A messages carry no skill).
        Waits at most timeout_s; on timeout returns the events so far with
        timed_out=true (the task keeps running; use resubscribe to follow it).
        Returns conversation_id, events, final_state, error and timed_out.
        """
        try:
            target = await resolve(agent)
            profile = _faults(faults)
            if conversation_id:
                await wb.conversations.get(conversation_id)
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
            skill_id=skill_id,
        )
        collected: list[Any] = []
        timed_out = False
        try:
            async with asyncio.timeout(timeout_s):
                async for event in wb.conversations.send(conv_id, parts, options):
                    collected.append(event)
        except TimeoutError:
            timed_out = True
        except Exception as exc:
            return {"conversation_id": conv_id, **_error(exc)}
        events = _events(collected)
        return {
            "conversation_id": conv_id,
            "events": events,
            "final_state": _final_state(events),
            "error": _last_error(events),
            "timed_out": timed_out,
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
    async def subscribe_task(agent: str, task_id: str, timeout_s: float = 30) -> dict[str, Any]:
        """Resubscribe to a running task (SubscribeToTask) and collect its events.

        Stops at the end of the stream or after timeout_s, returning the events
        so far with timed_out=true.
        """
        events: list[dict[str, Any]] = []
        try:
            agent_id = (await resolve(agent)).id
            async with asyncio.timeout(timeout_s):
                async for e in wb.tasks.subscribe(agent_id, task_id):
                    events.append(e)
        except TimeoutError:
            return {"events": events, "timed_out": True}
        except Exception as exc:
            return {"events": events, **_error(exc)}
        return {"events": events, "timed_out": False}

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

    async def card_of(agent: str) -> tuple[AgentOut, Any]:
        from a2a_workbench.core.a2a_json import card_from_json

        out = await resolve(agent)
        return out, card_from_json((await wb.agents.row(out.id)).card)

    @server.tool()
    async def auth_status(agent: str) -> dict[str, Any]:
        """Show the agent's security schemes, requirement alternatives and stored credentials.

        status is no_auth, signed_in or sign_in_needed; missing lists schemes
        still needing a credential. Credentials appear only as masked previews.
        """
        try:
            out, card = await card_of(agent)
            return (await wb.auth.overview(out.id, card)).model_dump(mode="json")
        except Exception as exc:
            return _error(exc)

    @server.tool()
    async def set_credential(
        agent: str,
        scheme: str,
        api_key: str | None = None,
        username: str | None = None,
        password: str | None = None,
        token: str | None = None,
        access_token: str | None = None,
        cert_pem: str | None = None,
        key_pem: str | None = None,
        ca_pem: str | None = None,
    ) -> dict[str, Any]:
        """Store a credential for one of the card's security schemes; returns its masked preview.

        Give api_key (apiKey), username+password (HTTP Basic), token (HTTP Bearer,
        or an OAuth access token for OAuth/OIDC schemes), access_token, or
        cert_pem+key_pem[+ca_pem] (mutualTLS).
        """
        from a2a_workbench.core.auth.service import credential_values

        try:
            out, card = await card_of(agent)
            kind, secret = credential_values(
                card,
                scheme,
                api_key=api_key,
                username=username,
                password=password,
                token=token,
                access_token=access_token,
                cert_pem=cert_pem,
                key_pem=key_pem,
                ca_pem=ca_pem,
            )
            info = await wb.auth.set_credential(out.id, card, scheme, kind, secret)
            return info.model_dump(mode="json")
        except Exception as exc:
            return _error(exc)

    @server.tool()
    async def sign_in(
        agent: str,
        scheme: str,
        client_id: str,
        client_secret: str | None = None,
        scopes: list[str] | None = None,
        username: str | None = None,
        password: str | None = None,
        auth_method: str = "client_secret_post",
    ) -> dict[str, Any]:
        """Sign in with the OAuth flow the scheme declares.

        client_credentials and password complete at once and return the masked
        credential. device_code returns flow_id, user_code and verification_uri:
        a person opens the URI and enters the code, then call poll_sign_in(flow_id).
        Browser flows (authorization code, implicit, OpenID Connect) need a
        person at a browser: use the web UI or `a2a-workbench auth login`.
        """
        try:
            out, card = await card_of(agent)
            flow = wb.auth.flow_for(card, scheme)
            if flow in ("client_credentials", "password"):
                info = await wb.auth.sign_in(
                    out.id,
                    scheme,
                    flow=flow,
                    client_id=client_id,
                    client_secret=client_secret,
                    scopes=scopes or [],
                    auth_method=auth_method,
                    username=username,
                    password=password,
                    card=card,
                )
                return info.model_dump(mode="json")
            if flow == "device_code":
                device = await wb.auth.start_device_flow(
                    out.id,
                    scheme,
                    client_id=client_id,
                    client_secret=client_secret,
                    scopes=scopes or [],
                    card=card,
                )
                return device.model_dump(mode="json")
            return {
                "error": {
                    "category": "workbench",
                    "message": f"'{scheme}' uses the {flow} flow, which needs a browser: sign in "
                    f"from the web UI or run `a2a-workbench auth login {agent} {scheme}`",
                }
            }
        except Exception as exc:
            return _error(exc)

    @server.tool()
    async def poll_sign_in(flow_id: str) -> dict[str, Any]:
        """Poll a device-code sign-in once: status is pending or signed_in (errors are returned)."""
        try:
            return {"status": await wb.auth.poll_device_flow(flow_id)}
        except Exception as exc:
            return _error(exc)

    @server.tool()
    async def sign_out(agent: str, scheme: str) -> dict[str, Any]:
        """Remove the stored credential for a scheme."""
        try:
            out = await resolve(agent)
            await wb.credentials.delete(out.id, scheme)
            return {"removed": scheme}
        except Exception as exc:
            return _error(exc)

    @server.tool()
    async def auth_probe(agent: str) -> dict[str, Any]:
        """Check the agent enforces its declared authentication.

        Calls GetTask on a random id without credentials, with wrong ones and
        with yours; each result has an outcome (pass, fail or skip) and a detail.
        """
        try:
            out, card = await card_of(agent)
            results = await wb.auth.probe(out.id, card, out.selected_interface_url)
            return {"results": [r.model_dump() for r in results]}
        except Exception as exc:
            return _error(exc)

    @server.tool()
    async def assistant_providers() -> dict[str, Any]:
        """List the Assistant's LLM providers and whether each has a key (masked)."""
        return {"providers": [p.model_dump(mode="json") for p in await wb.provider_keys.list()]}

    @server.tool()
    async def assist(
        goal: str,
        agents: list[str] | None = None,
        provider: str = "anthropic",
        model: str | None = None,
        response_mode: str = "rewrite",
        session_id: str | None = None,
        timeout_s: float = 300,
    ) -> dict[str, Any]:
        """Let an orchestrator LLM call A2A agents as tools, following A2A client rules.

        Give agents (URLs, ids or names) to start a chat, or session_id to
        continue one (for example to answer an agent's question in
        pass-through mode). response_mode is "rewrite" (the Assistant answers)
        or "pass_through" (agents' output goes to the user verbatim). Each step
        (tool_call, rejected_call, tool_result with conversation_id and ids,
        agent_output, paused, limit, error, done) is returned; list_exchanges on
        a step's conversation_id shows the wire traffic. Needs a provider key
        (see assistant_providers).
        """
        from a2a_workbench.core.assistant.service import SessionIn

        try:
            sid = session_id
            if sid is None:
                ids = [(await resolve(a)).id for a in agents or []]
                created = await wb.assistant.create(
                    SessionIn(
                        provider=provider,
                        model=model,
                        response_mode=response_mode,  # type: ignore[arg-type]
                        agent_ids=ids,
                        title=goal[:80],
                    )
                )
                sid = created.id
            steps: list[Any] = []
            timed_out = False
            try:
                async with asyncio.timeout(timeout_s):
                    async for step in wb.assistant.send(sid, goal):
                        steps.append(step.model_dump(mode="json"))
            except TimeoutError:
                timed_out = True
            session = await wb.assistant.get(sid)
        except Exception as exc:
            return _error(exc)
        done = next((s for s in reversed(steps) if s["kind"] == "done"), None)
        failed = next((s for s in reversed(steps) if s["kind"] == "error"), None)
        return {
            "session_id": sid,
            "status": session.status,
            "pending": session.pending,
            "final_text": done["data"]["text"] if done else None,
            "error": failed["data"] if failed else None,
            "timed_out": timed_out,
            "steps": steps,
        }

    @server.tool()
    async def integration_guide(agent: str, target: str | None = None) -> dict[str, Any]:
        """Code for calling an agent from your own agent, plus guidance and readiness.

        target is sdk (plain a2a-sdk), adk, langgraph, openai (Agents SDK) or claude
        (Agent SDK); with a target, returns its code, install line and env vars,
        otherwise every snippet. The code follows the A2A client rules (ids,
        follow-ups, resubscribe, artifacts as results, auth_required) and reads
        secrets from environment variables.
        """
        try:
            guide = await wb.integrate.guide((await resolve(agent)).id)
        except Exception as exc:
            return _error(exc)
        body = guide.model_dump(mode="json")
        if target is None:
            return body
        if target not in body["snippets"]:
            return {"error": {"category": "workbench", "message": f"unknown target '{target}'"}}
        snippet = body["snippets"][target]
        return {
            "agent": body["agent"],
            "card_url": body["card_url"],
            **snippet,
            "guidance": body["guidance"],
            "readiness": body["readiness"],
        }

    @server.tool()
    async def delete_conversation(conversation_id: str) -> dict[str, Any]:
        """Delete an agent conversation with its events and recorded exchanges."""
        try:
            await wb.conversations.delete(conversation_id)
        except Exception as exc:
            return _error(exc)
        return {"deleted": conversation_id}

    @server.tool()
    async def delete_assistant_chat(session_id: str) -> dict[str, Any]:
        """Delete an Assistant chat with its steps and recorded LLM calls."""
        try:
            await wb.assistant.delete(session_id)
        except Exception as exc:
            return _error(exc)
        return {"deleted": session_id}

    @server.tool()
    async def fault_presets() -> dict[str, Any]:
        """List the built-in network fault presets usable as send_message(faults=...)."""
        return {"presets": [p.model_dump(mode="json") for p in PRESETS.values()]}

    return server
