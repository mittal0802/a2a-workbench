"""Client code, generated from an Agent Card, for calling the agent from another agent.

Every snippet calls the agent through the official ``a2a-sdk`` and follows
the A2A client rules: interface selection (§8.3.2), credentials on every
request (§7.3), server-issued context ids (§3.4.1), continuing interrupted
tasks (§3.4.3), follow-ups after terminal states (Life of a Task),
resubscribing after a dropped stream (§3.5.2), artifacts as results (§3.7) and
delegating ``auth_required`` to the caller (§7.6.2). Secrets are read from
environment variables and never written into the code.
"""

import json
import re
from typing import Literal

from a2a.types import AgentCard
from pydantic import BaseModel

from a2a_workbench.core.assistant.tools import describe_agent
from a2a_workbench.core.auth.requirements import requirement_alternatives

Target = Literal["sdk", "adk", "langgraph", "openai", "claude"]
TARGETS: tuple[Target, ...] = ("sdk", "adk", "langgraph", "openai", "claude")
TARGET_NAMES: dict[str, str] = {
    "sdk": "Plain a2a-sdk",
    "adk": "Google ADK",
    "langgraph": "LangGraph / LangChain",
    "openai": "OpenAI Agents SDK",
    "claude": "Claude Agent SDK",
}
_INSTALL: dict[str, str] = {
    "sdk": 'pip install "a2a-sdk[http-server]>=1.2" httpx',
    "adk": 'pip install "google-adk[a2a]" "a2a-sdk>=1.2" httpx',
    "langgraph": 'pip install "a2a-sdk>=1.2" httpx langgraph langchain-core "langchain[anthropic]"',
    "openai": 'pip install "a2a-sdk>=1.2" httpx openai-agents',
    "claude": 'pip install "a2a-sdk>=1.2" httpx claude-agent-sdk',
}


class Snippet(BaseModel):
    """Generated code for one target, how to install it, and the environment variables it reads."""

    target: Target
    language: str = "python"
    install: str
    code: str
    env: dict[str, str]


def _env_prefix(scheme: str) -> str:
    return "A2A_" + re.sub(r"[^A-Za-z0-9]+", "_", scheme).strip("_").upper()


def _ident(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "agent"
    return slug if not slug[0].isdigit() else f"agent_{slug}"


def _auth_code(card: AgentCard) -> tuple[str, dict[str, str]]:
    """Return the body of ``credentials()`` for the card's first requirement alternative."""
    alternatives = requirement_alternatives(card)
    if not alternatives or not alternatives[0]:
        return (
            "    # The card declares no security requirement: nothing to send.\n"
            "    return {}, {}\n",
            {},
        )
    lines = [
        "    # A2A §7.3: credentials for the card's first security requirement, on every request.",
        "    headers: dict[str, str] = {}",
        "    http_kwargs: dict = {}",
    ]
    env: dict[str, str] = {}
    cookies: list[str] = []
    for name, scopes in alternatives[0].items():
        scheme = card.security_schemes.get(name)
        if scheme is None:
            continue
        prefix = _env_prefix(name)
        kind = scheme.WhichOneof("scheme")
        if kind == "api_key_security_scheme":
            spec = scheme.api_key_security_scheme
            var = f"{prefix}_API_KEY"
            env[var] = f"API key for scheme '{name}' ({spec.location} '{spec.name}')"
            if spec.location == "query":
                lines.append(
                    f'    http_kwargs.setdefault("params", {{}})[{spec.name!r}] = os.environ[{var!r}]'
                )
            elif spec.location == "cookie":
                cookies.append(f'f"{spec.name}={{os.environ[{var!r}]}}"')
            else:
                lines.append(f"    headers[{spec.name!r}] = os.environ[{var!r}]")
        elif kind == "http_auth_security_scheme":
            if scheme.http_auth_security_scheme.scheme.lower() == "basic":
                env[f"{prefix}_USERNAME"] = f"Username for scheme '{name}' (HTTP Basic)"
                env[f"{prefix}_PASSWORD"] = f"Password for scheme '{name}' (HTTP Basic)"
                lines.append(
                    f'    pair = f"{{os.environ[{prefix + "_USERNAME"!r}]}}:{{os.environ[{prefix + "_PASSWORD"!r}]}}"'
                )
                lines.append(
                    '    headers["Authorization"] = "Basic " + base64.b64encode(pair.encode()).decode()'
                )
            else:
                var = f"{prefix}_TOKEN"
                env[var] = f"Bearer token for scheme '{name}' (HTTP Bearer)"
                lines.append(f'    headers["Authorization"] = f"Bearer {{os.environ[{var!r}]}}"')
        elif kind == "oauth2_security_scheme":
            flows = scheme.oauth2_security_scheme.flows
            flow = flows.WhichOneof("flow")
            if flow == "client_credentials":
                token_url = flows.client_credentials.token_url
                env[f"{prefix}_CLIENT_ID"] = f"OAuth client id for scheme '{name}'"
                env[f"{prefix}_CLIENT_SECRET"] = f"OAuth client secret for scheme '{name}'"
                lines += [
                    "    # OAuth 2.0 client credentials (RFC 6749 §4.4) at the card's token URL.",
                    f"    token = await http.post({token_url!r}, data={{",
                    '        "grant_type": "client_credentials",',
                    f'        "client_id": os.environ[{prefix + "_CLIENT_ID"!r}],',
                    f'        "client_secret": os.environ[{prefix + "_CLIENT_SECRET"!r}],',
                    f'        "scope": {" ".join(scopes)!r},',
                    "    })",
                    "    token.raise_for_status()",
                    '    headers["Authorization"] = f"Bearer {token.json()[\'access_token\']}"',
                ]
            else:
                var = f"{prefix}_ACCESS_TOKEN"
                where = {
                    "authorization_code": "the authorization code flow with PKCE",
                    "device_code": "the device code flow",
                    "password": "the password flow",
                    "implicit": "the implicit flow",
                }.get(flow or "", "the scheme's OAuth flow")
                env[var] = f"OAuth access token for scheme '{name}', obtained with {where}"
                lines.append(
                    f"    # Obtain the token with {where}; scopes: {' '.join(scopes) or 'none'}."
                )
                lines.append(f'    headers["Authorization"] = f"Bearer {{os.environ[{var!r}]}}"')
        elif kind == "open_id_connect_security_scheme":
            var = f"{prefix}_ACCESS_TOKEN"
            env[var] = f"OpenID Connect access token for scheme '{name}'"
            url = scheme.open_id_connect_security_scheme.open_id_connect_url
            lines.append(f"    # Sign in with OpenID Connect ({url}) and pass the access token.")
            lines.append(f'    headers["Authorization"] = f"Bearer {{os.environ[{var!r}]}}"')
        elif kind == "mtls_security_scheme":
            env[f"{prefix}_CERT"] = f"Client certificate PEM path for scheme '{name}'"
            env[f"{prefix}_KEY"] = f"Client private key PEM path for scheme '{name}'"
            env[f"{prefix}_CA"] = "Optional CA bundle path to verify the agent"
            lines.append(
                f'    http_kwargs["cert"] = (os.environ[{prefix + "_CERT"!r}], os.environ[{prefix + "_KEY"!r}])'
            )
            lines.append(f'    http_kwargs["verify"] = os.environ.get({prefix + "_CA"!r}, True)')
    if cookies:
        lines.append(f'    headers["Cookie"] = "; ".join([{", ".join(cookies)}])')
    lines.append("    return headers, http_kwargs")
    return "\n".join(lines) + "\n", env


def _bindings(card: AgentCard) -> tuple[list[str], bool]:
    offered = [i.protocol_binding for i in card.supported_interfaces]
    http = [b for b in ("JSONRPC", "HTTP+JSON") if b in offered]
    if http or "GRPC" not in offered:
        return ["JSONRPC", "HTTP+JSON"], False
    return ["GRPC"], True


_CORE = '''"""Call __NAME__ over A2A from your own code or agent.

Generated by A2A Workbench from the agent card at __CARD_URL__.
Install: __INSTALL__
"""

import asyncio
import base64  # noqa: F401  (used by HTTP Basic credentials)
import json
import os
import uuid
from urllib.parse import urlsplit

import httpx
from a2a.client import A2ACardResolver, A2AClientError, ClientCallContext, ClientConfig, ClientFactory
from a2a.types import Message, Part, Role, SendMessageRequest, SubscribeToTaskRequest, TaskState
from google.protobuf.json_format import MessageToDict, ParseDict

CARD_URL = __CARD_URL_LITERAL__
TERMINAL = {
    TaskState.TASK_STATE_COMPLETED,
    TaskState.TASK_STATE_FAILED,
    TaskState.TASK_STATE_CANCELED,
    TaskState.TASK_STATE_REJECTED,
}


class AuthRequired(Exception):
    """The agent needs authorization to continue the task (TASK_STATE_AUTH_REQUIRED).

    A2A §7.6.2: resolve it (sign in, approve) or pass it up to your own caller,
    then continue the same task with ``call_agent`` and the same session.
    """


class AgentSession:
    """Ids the agent returned, kept between calls (A2A §3.4)."""

    def __init__(self) -> None:
        self.context_id: str | None = None  # server-issued; never invent one (§3.4.1)
        self.open_task_id: str | None = None  # a task waiting for input or sign-in
        self.last_task_id: str | None = None  # the last finished task, for follow-ups


async def credentials(http: httpx.AsyncClient) -> tuple[dict[str, str], dict]:
    """Return (headers, httpx client options) that authenticate calls to the agent."""
__AUTH__

def _texts(message) -> list[str]:
    return [p.text for p in message.parts if p.HasField("text")]


def _fold(event, session: AgentSession, out: dict) -> None:
    kind = event.WhichOneof("payload")
    if kind == "task":
        task = event.task
        session.context_id = task.context_id or session.context_id
        out["task_id"], out["state"] = task.id, task.status.state
        for artifact in task.artifacts:
            out["artifacts"][artifact.artifact_id] = MessageToDict(artifact)
        if task.status.HasField("message"):
            out["messages"] += _texts(task.status.message)
    elif kind == "message":
        session.context_id = event.message.context_id or session.context_id
        out["messages"] += _texts(event.message)
    elif kind == "status_update":
        out["task_id"], out["state"] = event.status_update.task_id, event.status_update.status.state
        if event.status_update.status.HasField("message"):
            out["messages"] += _texts(event.status_update.status.message)
    elif kind == "artifact_update":
        chunk = MessageToDict(event.artifact_update.artifact)
        current = out["artifacts"].get(chunk.get("artifactId"))
        if event.artifact_update.append and current is not None:
            current.setdefault("parts", []).extend(chunk.get("parts", []))
        else:
            out["artifacts"][chunk.get("artifactId")] = chunk


async def call_agent(text: str, session: AgentSession, data: dict | None = None) -> dict:
    """Send ``text`` (and optional JSON ``data``) to the agent and return its result.

    Returns ``{"state", "question", "text", "artifacts", "messages", "task_id",
    "context_id"}``: ``text`` joins the artifacts' text (results are artifacts,
    A2A §3.7); ``question`` is set when the agent needs more input.

    Raises:
        AuthRequired: when the agent asks for authorization (A2A §7.6.2).
    """
    async with httpx.AsyncClient(timeout=120) as bootstrap:
        headers, http_kwargs = await credentials(bootstrap)
    async with httpx.AsyncClient(timeout=120, **http_kwargs) as http:
        url = urlsplit(CARD_URL)
        resolver = A2ACardResolver(http, f"{url.scheme}://{url.netloc}", url.path)
        card = await resolver.get_agent_card()
        streaming = bool(card.capabilities.streaming)
        # A2A §8.3.2: the factory uses the first interface in the card's order
        # whose binding this client supports.
        config = ClientConfig(
            httpx_client=http,
            streaming=streaming,
            supported_protocol_bindings=__BINDINGS__,__GRPC__
        )
        client = ClientFactory(config).create(card)
        message = Message(message_id=uuid.uuid4().hex, role=Role.ROLE_USER, parts=[Part(text=text)])
        if data is not None:
            message.parts.append(ParseDict({"data": data}, Part()))
        if session.context_id:
            message.context_id = session.context_id
        if session.open_task_id:
            # A2A §3.4.3: answer an input_required / auth_required task on the same task.
            message.task_id = session.open_task_id
        elif session.last_task_id:
            # Life of a Task: finished tasks are immutable; a follow-up is a new task in
            # the same context that references the earlier one.
            message.reference_task_ids.append(session.last_task_id)
        context = ClientCallContext(service_parameters=headers)
        out: dict = {"state": None, "task_id": None, "artifacts": {}, "messages": []}
        try:
            async for event in client.send_message(SendMessageRequest(message=message), context=context):
                _fold(event, session, out)
        except (httpx.TransportError, A2AClientError):
            if not (streaming and out["task_id"]):
                raise
            # A2A §3.5.2: the stream dropped; open a new one for the same task.
            async for event in client.subscribe(SubscribeToTaskRequest(id=out["task_id"]), context=context):
                _fold(event, session, out)
        finally:
            await client.close()

    state = out["state"]
    waiting = state in (TaskState.TASK_STATE_INPUT_REQUIRED, TaskState.TASK_STATE_AUTH_REQUIRED)
    session.open_task_id = out["task_id"] if waiting else None
    if state in TERMINAL:
        session.last_task_id = out["task_id"]
    artifacts = list(out["artifacts"].values())
    result = {
        "state": TaskState.Name(state) if state is not None else "MESSAGE",
        "question": out["messages"][-1] if waiting and out["messages"] else None,
        "text": "\\n".join(p.get("text", "") for a in artifacts for p in a.get("parts", []) if "text" in p),
        "artifacts": artifacts,
        "messages": out["messages"],
        "task_id": out["task_id"],
        "context_id": session.context_id,
    }
    if state == TaskState.TASK_STATE_AUTH_REQUIRED:
        raise AuthRequired(result["question"] or "The agent needs authorization.")
    return result
'''

_SDK_MAIN = '''

async def main() -> None:
    """Demo: A2A_MESSAGE, then A2A_REPLY if the agent asks, then A2A_FOLLOW_UP."""
    session = AgentSession()
    result = await call_agent(os.environ.get("A2A_MESSAGE", "hello"), session)
    print(json.dumps(result, indent=2, default=str))
    if result["question"] and os.environ.get("A2A_REPLY"):
        result = await call_agent(os.environ["A2A_REPLY"], session)
        print(json.dumps(result, indent=2, default=str))
    if os.environ.get("A2A_FOLLOW_UP"):
        result = await call_agent(os.environ["A2A_FOLLOW_UP"], session)
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
'''

_ADK = '''

# --- Google ADK: the agent as a sub-agent ------------------------------------
# ADK's RemoteA2aAgent speaks A2A itself (through a2a-sdk) and keeps the
# context and task ids for you; call_agent above is useful outside ADK.
from google.adk.agents import Agent
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent


async def build_root_agent() -> Agent:
    """Return an ADK agent that can delegate to __NAME__."""
    async with httpx.AsyncClient(timeout=120) as bootstrap:
        headers, http_kwargs = await credentials(bootstrap)
    remote = RemoteA2aAgent(
        name=__IDENT_LITERAL__,
        description=__DESCRIPTION__,
        agent_card=CARD_URL,
        httpx_client=httpx.AsyncClient(timeout=120, headers=headers, **http_kwargs),
    )
    return Agent(
        model="gemini-2.5-flash",
        name="orchestrator",
        instruction=__INSTRUCTIONS__,
        sub_agents=[remote],
    )
'''

_LANGGRAPH = '''

# --- LangGraph / LangChain: the agent as a tool --------------------------------
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

_session = AgentSession()


@tool
async def __IDENT__(request: str) -> str:
    """__TOOL_DOC__"""
    try:
        return json.dumps(await call_agent(request, _session), default=str)
    except AuthRequired as exc:
        return json.dumps({"state": "TASK_STATE_AUTH_REQUIRED", "question": str(exc)})


orchestrator = create_react_agent(
    "anthropic:claude-sonnet-5-5", tools=[__IDENT__], prompt=__INSTRUCTIONS__
)
'''

_OPENAI = '''

# --- OpenAI Agents SDK: the agent as a function tool ---------------------------
from agents import Agent, Runner, function_tool

_session = AgentSession()


@function_tool
async def __IDENT__(request: str) -> str:
    """__TOOL_DOC__"""
    try:
        return json.dumps(await call_agent(request, _session), default=str)
    except AuthRequired as exc:
        return json.dumps({"state": "TASK_STATE_AUTH_REQUIRED", "question": str(exc)})


orchestrator = Agent(name="Orchestrator", instructions=__INSTRUCTIONS__, tools=[__IDENT__])


async def run(goal: str) -> str:
    """Run the orchestrator on ``goal`` and return its final answer."""
    return (await Runner.run(orchestrator, goal)).final_output
'''

_CLAUDE = '''

# --- Claude Agent SDK: the agent as an in-process MCP tool ---------------------
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, create_sdk_mcp_server, tool

_session = AgentSession()


@tool(__IDENT_LITERAL__, __DESCRIPTION__, {"request": str})
async def __IDENT__(args: dict) -> dict:
    try:
        result = await call_agent(args["request"], _session)
    except AuthRequired as exc:
        result = {"state": "TASK_STATE_AUTH_REQUIRED", "question": str(exc)}
    return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}


OPTIONS = ClaudeAgentOptions(
    system_prompt=__INSTRUCTIONS__,
    mcp_servers={"a2a": create_sdk_mcp_server(name="a2a", version="1.0.0", tools=[__IDENT__])},
    allowed_tools=[__ALLOWED__],
)


async def run(goal: str) -> None:
    """Ask Claude to reach ``goal``, printing its messages."""
    async with ClaudeSDKClient(options=OPTIONS) as client:
        await client.query(goal)
        async for message in client.receive_response():
            print(message)
'''

ORCHESTRATOR_INSTRUCTIONS = (
    "You can call an A2A agent through a tool. Pass the user's request as-is, only resolving "
    "references to earlier turns; never add details. If the result has a question, answer it "
    "only from what the user said, otherwise ask the user and send their answer with the tool "
    "again. Results are the artifacts; messages are progress. If the state is "
    "TASK_STATE_AUTH_REQUIRED, tell the user which sign-in is needed."
)


def render(card: AgentCard, card_url: str, target: Target) -> Snippet:
    """Return the snippet for ``target`` calling the agent whose card is at ``card_url``.

    Raises:
        ValueError: for an unknown target.
    """
    if target not in TARGETS:
        raise ValueError(f"unknown target '{target}' (use one of {', '.join(TARGETS)})")
    auth, env = _auth_code(card)
    bindings, grpc = _bindings(card)
    grpc_line = (
        "\n            grpc_channel_factory=lambda target: __import__('grpc').aio.insecure_channel(target),"
        if grpc
        else ""
    )
    code = (
        _CORE.replace("__NAME__", card.name)
        .replace("__CARD_URL_LITERAL__", json.dumps(card_url))
        .replace("__CARD_URL__", card_url)
        .replace("__INSTALL__", _INSTALL[target])
        .replace("__AUTH__", auth)
        .replace("__BINDINGS__", json.dumps(bindings))
        .replace("__GRPC__", grpc_line)
    )
    extra = {
        "sdk": _SDK_MAIN,
        "adk": _ADK,
        "langgraph": _LANGGRAPH,
        "openai": _OPENAI,
        "claude": _CLAUDE,
    }[target]
    ident = _ident(card.name)
    description = describe_agent(card)
    code += (
        extra.replace("__NAME__", card.name)
        .replace("__IDENT_LITERAL__", json.dumps(ident))
        .replace("__IDENT__", ident)
        .replace("__DESCRIPTION__", json.dumps(description))
        .replace("__TOOL_DOC__", description.replace("\\", "\\\\").replace('"""', '\\"\\"\\"'))
        .replace("__INSTRUCTIONS__", json.dumps(ORCHESTRATOR_INSTRUCTIONS))
        .replace("__ALLOWED__", json.dumps(f"mcp__a2a__{ident}"))
    )
    return Snippet(target=target, install=_INSTALL[target], code=code, env=env)
