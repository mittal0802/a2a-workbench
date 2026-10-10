"""Agent zoo: A2A agents built with the official SDK server, for tests and demos."""

import asyncio
import base64
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import a2a.client  # noqa: F401  # must load before a2a.compat.v0_3.grpc_handler (SDK import cycle)
import grpc
import httpx
from a2a.compat.v0_3 import a2a_v0_3_pb2_grpc
from a2a.compat.v0_3.grpc_handler import CompatGrpcHandler
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import GrpcHandler
from a2a.server.routes import (
    create_agent_card_routes,
    create_jsonrpc_routes,
    create_rest_routes,
)
from a2a.server.tasks import (
    BasePushNotificationSender,
    InMemoryPushNotificationConfigStore,
    InMemoryTaskStore,
    TaskUpdater,
)
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentExtension,
    AgentInterface,
    AgentProvider,
    AgentSkill,
    Message,
    Part,
    Role,
    SecurityRequirement,
    StringList,
    Task,
    TaskState,
    TaskStatus,
    a2a_pb2_grpc,
)
from a2a.utils.signing import create_agent_card_signer
from cryptography.hazmat.primitives.asymmetric import ec
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Value
from jwt.algorithms import ECAlgorithm
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from a2a_workbench.fixtures.auth import ZooAuthMiddleware, ZooGrpcAuthInterceptor, security_for
from a2a_workbench.fixtures.broken import (
    BREAKS,
    BrokenHandler,
    BrokenPushSender,
    apply_card_breaks,
    tamper_signed_card,
)

KEY_ID = "zoo-1"
ZOO_EXTENSION = "https://github.com/mittal0802/a2a-workbench/extensions/zoo-inspect/v1"
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _data(obj: Any) -> Value:
    return ParseDict(obj, Value())


def _token_scopes(context: RequestContext) -> list[str]:
    """Return the scopes of the caller's bearer JWT (already verified by the middleware)."""
    import jwt as pyjwt

    headers = context.call_context.state.get("headers", {}) if context.call_context else {}
    auth = headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return []
    try:
        claims = pyjwt.decode(auth[7:], options={"verify_signature": False})
    except pyjwt.PyJWTError:
        return []
    return str(claims.get("scope", "")).split()


def _split_store_handler(handler: Any, card: AgentCard, breaks: frozenset[str]) -> Any:
    return BrokenHandler(
        breaks=breaks,
        agent_executor=handler.agent_executor,
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )


class ZooExecutor(AgentExecutor):
    """Agent whose behaviour is chosen by the first word of the user's text.

    ``echo`` (default) replies with an artifact repeating the text; ``stream``
    sends a four-chunk artifact; ``ask`` enters ``input_required`` and completes
    on the reply; ``message`` answers with a direct Message; ``data`` and
    ``file`` return structured and file parts; ``fail`` and ``reject`` end in
    those states; ``slow <seconds>`` works for that long; ``note`` completes with its
    output only in the final status message (no artifact); ``long`` streams ten
    artifact chunks 150 ms apart; ``stall <seconds>`` goes silent after
    starting work; ``auth`` enters
    ``auth_required``; ``inspect`` returns a data artifact describing the
    received message, configuration and requested extensions. ``breaks`` (from
    ``fixtures.broken``) changes behaviour on purpose.
    """

    def __init__(
        self, breaks: frozenset[str] = frozenset(), *, required_extension: bool = False
    ) -> None:
        self.breaks = breaks
        self.required_extension = required_extension

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Run the behaviour selected by the user text and publish its events.

        With ``required_extension``, a request that does not activate the zoo
        extension is refused with ExtensionSupportRequiredError (A2A §3.3.4).
        """
        if (
            self.required_extension
            and "extension-not-enforced" not in self.breaks
            and ZOO_EXTENSION not in context.requested_extensions
        ):
            from a2a.utils.errors import ExtensionSupportRequiredError

            raise ExtensionSupportRequiredError(message=f"activate {ZOO_EXTENSION}")
        text = context.get_user_input().strip()
        word, _, rest = text.partition(" ")
        word = word.lower()
        task = context.current_task
        updater = TaskUpdater(event_queue, context.task_id or "", context.context_id or "")

        if word == "message" and task is None:
            await event_queue.enqueue_event(
                Message(
                    message_id=uuid.uuid4().hex,
                    role=Role.ROLE_AGENT,
                    context_id=context.context_id or "",
                    parts=[Part(text=f"Direct reply: {rest or 'hello'}")],
                )
            )
            return

        if task is None:
            await event_queue.enqueue_event(
                Task(
                    id=context.task_id,
                    context_id=context.context_id,
                    status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
                    history=[context.message] if context.message else [],
                )
            )
        elif task.status.state == TaskState.TASK_STATE_INPUT_REQUIRED:
            await updater.start_work()
            await updater.add_artifact([Part(text=f"You chose: {text}")], name="answer")
            await updater.complete()
            return

        await updater.start_work(updater.new_agent_message([Part(text="Working on it…")]))
        await self._behave(word, rest, text, context, updater)

    async def _behave(
        self, word: str, rest: str, text: str, context: RequestContext, updater: TaskUpdater
    ) -> None:
        if word == "stream":
            chunks = ["Streaming ", "in ", "four ", "pieces."]
            for i, chunk in enumerate(chunks):
                await asyncio.sleep(0.05)
                await updater.add_artifact(
                    [Part(text=chunk)],
                    artifact_id="stream-1",
                    name="streamed",
                    append=i > 0,
                    last_chunk=i == len(chunks) - 1,
                )
            await updater.complete()
        elif word == "long":
            for i in range(10):
                await asyncio.sleep(0.15)
                await updater.add_artifact(
                    [Part(text=f"part {i + 1} ")],
                    artifact_id="long-1",
                    name="long",
                    append=i > 0,
                    last_chunk=i == 9,
                )
            await updater.complete()
        elif word == "note":
            await updater.complete(updater.new_agent_message([Part(text=f"Noted: {rest}")]))
        elif word == "stall":
            await asyncio.sleep(float(rest or "30"))
            await updater.complete()
        elif word == "hold":
            if "booking.write" not in _token_scopes(context):
                await updater.requires_auth(
                    updater.new_agent_message(
                        [Part(text="Holding a booking needs the booking.write scope.")]
                    )
                )
                return
            await updater.add_artifact([Part(text=f"Held {rest or 'the booking'}.")], name="hold")
            await updater.complete()
        elif word == "ask":
            await updater.requires_input(
                updater.new_agent_message([Part(text="Which option should I pick: A or B?")])
            )
        elif word == "data":
            await updater.add_artifact(
                [
                    Part(
                        data=_data({"ok": True, "items": [1, 2, 3]}),
                        media_type="application/json",
                    )
                ],
                name="data",
            )
            await updater.complete()
        elif word == "file":
            await updater.add_artifact(
                [
                    Part(raw=PNG_1PX, media_type="image/png", filename="pixel.png"),
                    Part(
                        url="https://a2a-protocol.org/",
                        media_type="text/html",
                        filename="a2a.html",
                    ),
                ],
                name="files",
            )
            await updater.complete()
        elif word == "fail":
            await updater.failed(updater.new_agent_message([Part(text="Something went wrong.")]))
        elif word == "reject":
            await updater.reject(updater.new_agent_message([Part(text="I won't do that.")]))
        elif word == "slow":
            await asyncio.sleep(float(rest or "5"))
            await updater.complete(updater.new_agent_message([Part(text="Finally done.")]))
        elif word == "auth":
            await updater.requires_auth(updater.new_agent_message([Part(text="Please sign in.")]))
        elif word == "inspect":
            report = {
                "message": MessageToDict(context.message) if context.message else None,
                "configuration": (
                    MessageToDict(context.configuration) if context.configuration else None
                ),
                "requestedExtensions": sorted(context.requested_extensions),
            }
            await updater.add_artifact(
                [Part(data=_data(json.loads(json.dumps(report))))], name="inspect"
            )
            await updater.complete()
        else:
            if "message-output" in self.breaks:
                await updater.complete(updater.new_agent_message([Part(text=text or "(empty)")]))
                return
            await updater.add_artifact([Part(text=text or "(empty)")], name="echo")
            await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Mark the task canceled."""
        await TaskUpdater(event_queue, context.task_id or "", context.context_id or "").cancel()


def build_zoo_card(
    base_url: str, grpc_target: str | None = None, protocol_version: str = "1.0"
) -> AgentCard:
    """Return the public card of the zoo agent served at ``base_url``.

    ``grpc_target`` (``host:port``) adds a gRPC interface; every interface
    declares ``protocol_version``.
    """
    card = AgentCard(
        name="Zoo agent",
        description="Reference A2A agent for testing A2A Workbench.",
        version="1.0.0",
        provider=AgentProvider(
            organization="A2A Workbench", url="https://github.com/mittal0802/a2a-workbench"
        ),
        documentation_url="https://github.com/mittal0802/a2a-workbench",
        supported_interfaces=[
            AgentInterface(
                url=f"{base_url}/a2a", protocol_binding="JSONRPC", protocol_version="1.0"
            ),
            AgentInterface(
                url=f"{base_url}/v1", protocol_binding="HTTP+JSON", protocol_version="1.0"
            ),
        ],
        capabilities=AgentCapabilities(
            streaming=True,
            extended_agent_card=protocol_version != "0.3",
            extensions=[
                AgentExtension(
                    uri=ZOO_EXTENSION,
                    description="Lists activated extensions in the inspect report",
                    required=False,
                )
            ],
        ),
        default_input_modes=["text/plain", "application/json", "image/png"],
        default_output_modes=["text/plain", "application/json", "image/png"],
        skills=[
            AgentSkill(
                id="echo",
                name="Echo",
                description="Repeats what you send.",
                tags=["test"],
                examples=["echo hello"],
            ),
            AgentSkill(
                id="stream",
                name="Stream",
                description="Streams a four-piece artifact.",
                tags=["test", "streaming"],
                examples=["stream"],
            ),
            AgentSkill(
                id="ask",
                name="Ask",
                description="Asks a question before finishing.",
                tags=["test"],
                examples=["ask"],
            ),
        ],
    )
    if grpc_target:
        card.supported_interfaces.append(
            AgentInterface(url=grpc_target, protocol_binding="GRPC", protocol_version="1.0")
        )
    for iface in card.supported_interfaces:
        iface.protocol_version = protocol_version
    return card


def build_zoo_app(
    base_url: str,
    *,
    signed: bool = True,
    card_path: str = "/.well-known/agent-card.json",
    grpc_port: int | None = None,
    legacy: bool = False,
    auth: str = "none",
    idp: Any = None,
    extended_configured: bool = True,
    push: bool = True,
    breaks: frozenset[str] = frozenset(),
    streaming: bool = True,
    required_extension: bool = False,
) -> Starlette:
    """Return an ASGI app serving the zoo agent, its card (at ``card_path``) and its JWKS.

    With ``grpc_port``, the app's lifespan also serves the agent over gRPC on
    that port of the base URL's host. With ``legacy``, the card declares A2A
    0.3 and every binding is served through the SDK's v0.3 compatibility layer.
    ``auth`` selects the security scheme the card declares and the A2A
    endpoints enforce (the card and JWKS stay public).

    With ``extended_configured=False`` the card still declares an extended card but
    none is configured, so GetExtendedAgentCard answers ExtendedAgentCardNotConfiguredError.
    ``breaks`` names deliberate violations from ``fixtures.broken.BREAKS``.
    """
    unknown = set(breaks) - set(BREAKS)
    if unknown:
        raise ValueError(f"unknown breaks: {', '.join(sorted(unknown))}")
    host = base_url.split("://", 1)[1].split(":", 1)[0]
    grpc_target = f"{host}:{grpc_port}" if grpc_port else None
    card = build_zoo_card(base_url, grpc_target, "0.3" if legacy else "1.0")
    card.capabilities.push_notifications = push
    card.capabilities.streaming = streaming
    if required_extension:
        card.capabilities.extensions[0].required = True
    if "auth-not-enforced" in breaks and auth == "none":
        from a2a.types import HTTPAuthSecurityScheme, SecurityScheme

        card.security_schemes["bearer"].CopyFrom(
            SecurityScheme(http_auth_security_scheme=HTTPAuthSecurityScheme(scheme="Bearer"))
        )
        card.security_requirements.append(SecurityRequirement(schemes={"bearer": StringList()}))
    apply_card_breaks(card, breaks, base_url)
    schemes, requirements = security_for(auth, idp.issuer if idp else None)
    for name, scheme in schemes.items():
        card.security_schemes[name].CopyFrom(scheme)
    card.security_requirements.extend(requirements)
    if auth in ("oauth", "oidc"):
        card.skills.append(
            AgentSkill(
                id="hold",
                name="Hold a booking",
                description="Holds a booking; needs the booking.write scope.",
                tags=["auth"],
                examples=["hold AI175"],
                security_requirements=[
                    SecurityRequirement(
                        schemes={
                            "oauth" if auth == "oauth" else "oidc": StringList(
                                list=["booking.write"]
                            )
                        }
                    )
                ],
            )
        )
    private_key = ec.generate_private_key(ec.SECP256R1())
    jwk = json.loads(ECAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": KEY_ID, "alg": "ES256", "use": "sig"})
    if signed:
        signer = create_agent_card_signer(
            private_key,  # type: ignore[arg-type]
            {
                "kid": KEY_ID,
                "alg": "ES256",
                "jku": f"{base_url}/.well-known/jwks.json",
                "typ": "JOSE",
            },
        )
        card = signer(card)
        tamper_signed_card(card, breaks)

    extended = AgentCard()
    extended.CopyFrom(card)
    del extended.signatures[:]
    extended.skills.append(
        AgentSkill(
            id="visa",
            name="Visa check",
            description="Only listed on the extended card.",
            tags=["extended"],
            examples=["echo visa"],
        )
    )
    push_store = (
        InMemoryPushNotificationConfigStore() if push or "push-undeclared-works" in breaks else None
    )
    sender_class = BrokenPushSender if "push-no-auth" in breaks else BasePushNotificationSender
    handler = BrokenHandler(
        breaks=breaks,
        agent_executor=ZooExecutor(breaks, required_extension=required_extension),
        task_store=InMemoryTaskStore(),
        agent_card=card,
        extended_agent_card=(
            extended if card.capabilities.extended_agent_card and extended_configured else None
        ),
        push_config_store=push_store,
        push_sender=(
            sender_class(httpx.AsyncClient(timeout=10), push_store) if push_store else None
        ),
    )

    async def jwks(_: Request) -> JSONResponse:
        return JSONResponse({"keys": [jwk]})

    routes = [
        *create_agent_card_routes(
            card,
            card_url=card_path,
            cache_control=None if "card-no-cache" in breaks else "public, max-age=300",
        ),
        Route("/.well-known/jwks.json", jwks),
        *create_jsonrpc_routes(handler, "/a2a", enable_v0_3_compat=legacy),
        *create_rest_routes(
            _split_store_handler(handler, card, breaks) if "split-stores" in breaks else handler,
            path_prefix="/v1",
            enable_v0_3_compat=legacy,
        ),
    ]

    @asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        server = None
        if grpc_target:
            server = grpc.aio.server(interceptors=[ZooGrpcAuthInterceptor(auth, idp)])
            if legacy:
                a2a_v0_3_pb2_grpc.add_A2AServiceServicer_to_server(
                    CompatGrpcHandler(handler), server
                )
            else:
                a2a_pb2_grpc.add_A2AServiceServicer_to_server(GrpcHandler(handler), server)
            server.add_insecure_port(grpc_target)
            await server.start()
        try:
            yield
        finally:
            if server is not None:
                await server.stop(grace=0)

    app = Starlette(routes=routes, lifespan=lifespan)
    app.add_middleware(
        ZooAuthMiddleware, mode=auth, idp=idp, challenge="no-challenge" not in breaks
    )
    return app
