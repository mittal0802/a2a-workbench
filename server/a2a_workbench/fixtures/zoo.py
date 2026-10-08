"""Agent zoo: A2A agents built with the official SDK server, for tests and demos."""

import asyncio
import base64
import json
from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandlerV2
from a2a.server.routes import (
    create_agent_card_routes,
    create_jsonrpc_routes,
    create_rest_routes,
)
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentProvider,
    AgentSkill,
    Part,
    Task,
    TaskState,
    TaskStatus,
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

KEY_ID = "zoo-1"
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _data(obj: Any) -> Value:
    return ParseDict(obj, Value())


class ZooExecutor(AgentExecutor):
    """Agent whose behaviour is chosen by the first word of the user's text.

    ``echo`` (default) replies with an artifact repeating the text; ``stream``
    sends a four-chunk artifact; ``ask`` enters ``input_required`` and completes
    on the reply; ``message`` answers with a direct Message; ``data`` and
    ``file`` return structured and file parts; ``fail`` and ``reject`` end in
    those states; ``slow <seconds>`` works for that long; ``auth`` enters
    ``auth_required``; ``inspect`` returns a data artifact describing the
    received message, configuration and requested extensions.
    """

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Run the behaviour selected by the user text and publish its events."""
        text = context.get_user_input().strip()
        word, _, rest = text.partition(" ")
        word = word.lower()
        task = context.current_task
        updater = TaskUpdater(event_queue, context.task_id or "", context.context_id or "")

        if word == "message" and task is None:
            await event_queue.enqueue_event(
                updater.new_agent_message([Part(text=f"Direct reply: {rest or 'hello'}")])
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
            await updater.add_artifact([Part(text=text or "(empty)")], name="echo")
            await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Mark the task canceled."""
        await TaskUpdater(event_queue, context.task_id or "", context.context_id or "").cancel()


def build_zoo_card(base_url: str) -> AgentCard:
    """Return the public card of the zoo agent served at ``base_url``."""
    return AgentCard(
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
        capabilities=AgentCapabilities(streaming=True),
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


def build_zoo_app(
    base_url: str, *, signed: bool = True, card_path: str = "/.well-known/agent-card.json"
) -> Starlette:
    """Return an ASGI app serving the zoo agent, its card (at ``card_path``) and its JWKS."""
    card = build_zoo_card(base_url)
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

    handler = DefaultRequestHandlerV2(
        agent_executor=ZooExecutor(), task_store=InMemoryTaskStore(), agent_card=card
    )

    async def jwks(_: Request) -> JSONResponse:
        return JSONResponse({"keys": [jwk]})

    routes = [
        *create_agent_card_routes(card, card_url=card_path),
        Route("/.well-known/jwks.json", jwks),
        *create_jsonrpc_routes(handler, "/a2a"),
        *create_rest_routes(handler, path_prefix="/v1"),
    ]
    return Starlette(routes=routes)
