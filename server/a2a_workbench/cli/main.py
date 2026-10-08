"""`a2a-workbench` command-line interface."""

import asyncio
import base64
import json
import mimetypes
import sys
import webbrowser
from collections.abc import Coroutine
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer

from a2a_workbench.cli.output import ExitCode, HumanPrinter, exit_code_for, print_json
from a2a_workbench.core.config import Settings
from a2a_workbench.core.connection.cards import CardFetchError
from a2a_workbench.core.conversations.errors import classify_error
from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.conversations.parts import (
    AnyPartInput,
    DataPartInput,
    FilePartInput,
    TextPartInput,
)
from a2a_workbench.core.registry.service import AgentExistsError, AgentNotFoundError, AgentOut
from a2a_workbench.core.workbench import Workbench

app = typer.Typer(
    no_args_is_help=True,
    help="Debug, test and conformance-check A2A agents.",
    pretty_exceptions_enable=False,
)
agents_app = typer.Typer(no_args_is_help=True, help="Manage registered agents.")
app.add_typer(agents_app, name="agents")

JsonFlag = Annotated[bool, typer.Option("--json", help="Machine-readable JSON output.")]


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def _fail(category: str, message: str, as_json: bool, code: ExitCode | None = None) -> NoReturn:
    if as_json:
        print_json({"error": {"category": category, "message": message}})
    else:
        typer.echo(f"error ({category}): {message}", err=True)
    raise typer.Exit(code if code is not None else exit_code_for(category))


def _card_failure(exc: CardFetchError, as_json: bool) -> NoReturn:
    _fail(classify_error(exc.cause)["category"], str(exc), as_json)


def _parse_json(value: str | None, option: str) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        typer.echo(f"{option} is not valid JSON: {exc}", err=True)
        raise typer.Exit(ExitCode.USAGE) from exc


@app.command()
def serve(
    host: Annotated[str | None, typer.Option(help="Interface to bind.")] = None,
    port: Annotated[int | None, typer.Option(help="Port to listen on.")] = None,
    open_browser: Annotated[
        bool, typer.Option("--open/--no-open", help="Open the UI in a browser.")
    ] = False,
) -> None:
    """Run the web UI and API."""
    import uvicorn

    from a2a_workbench.api.app import create_app

    settings = Settings()
    bind_host, bind_port = host or settings.host, port or settings.port
    if open_browser:
        webbrowser.open(f"http://{bind_host}:{bind_port}")
    uvicorn.run(create_app(settings), host=bind_host, port=bind_port, log_level="info")


@agents_app.command("add")
def agents_add(
    url: Annotated[str, typer.Argument(help="Agent base URL or agent card URL.")],
    card_path: Annotated[str | None, typer.Option(help="Card path relative to URL.")] = None,
    as_json: JsonFlag = False,
) -> None:
    """Register the agent at URL."""

    async def go() -> None:
        async with Workbench.open(Settings()) as wb:
            try:
                agent = await wb.agents.add(url, card_path)
            except CardFetchError as exc:
                _card_failure(exc, as_json)
            except AgentExistsError as exc:
                _fail("workbench", str(exc), as_json, ExitCode.USAGE)
            if as_json:
                print_json(agent.model_dump(mode="json"))
            else:
                typer.echo(
                    f"Registered {agent.name} ({agent.id}) via {agent.selected_interface_url}"
                )

    _run(go())


@agents_app.command("list")
def agents_list(as_json: JsonFlag = False) -> None:
    """List registered agents."""

    async def go() -> None:
        async with Workbench.open(Settings()) as wb:
            agents = await wb.agents.list()
        if as_json:
            print_json([a.model_dump(mode="json") for a in agents])
            return
        for a in agents:
            typer.echo(f"{a.id}  {a.name}  {a.base_url}  [{a.signature_status}]")

    _run(go())


@agents_app.command("remove")
def agents_remove(ref: Annotated[str, typer.Argument(help="Agent id, name or URL.")]) -> None:
    """Remove a registered agent and its history."""

    async def go() -> None:
        async with Workbench.open(Settings()) as wb:
            try:
                agent = await wb.agents.resolve(ref)
            except AgentNotFoundError as exc:
                _fail("workbench", str(exc), False, ExitCode.USAGE)
            await wb.agents.remove(agent.id)
        typer.echo(f"Removed {agent.name}")

    _run(go())


@app.command()
def card(
    target: Annotated[str, typer.Argument(help="Agent URL, card URL or registered agent.")],
    as_json: JsonFlag = False,
) -> None:
    """Fetch an agent card and verify its signature."""

    async def go() -> None:
        async with Workbench.open(Settings()) as wb:
            url, card_path = target, None
            try:
                agent = await wb.agents.resolve(target)
                url, card_path = agent.base_url, agent.card_path
            except AgentNotFoundError:
                pass
            try:
                preview = await wb.agents.preview(url, card_path)
            except CardFetchError as exc:
                _card_failure(exc, as_json)
        if as_json:
            print_json(preview.model_dump(mode="json"))
            return
        c = preview.card
        typer.echo(f"{c.get('name')} {c.get('version', '')} — {c.get('description', '')}")
        typer.echo(f"signature: {preview.signature_status}")
        for i in preview.interfaces:
            typer.echo(f"  {i.binding:<10} {i.protocol_version:<5} {i.url}")
        for s in c.get("skills", []):
            typer.echo(f"  skill {s.get('id')}: {s.get('name')} — {s.get('description', '')}")

    _run(go())


async def _resolve_or_register(wb: Workbench, target: str, as_json: bool) -> AgentOut:
    try:
        return await wb.agents.resolve(target)
    except AgentNotFoundError:
        pass
    try:
        agent = await wb.agents.add(target)
    except CardFetchError as exc:
        _card_failure(exc, as_json)
    if not as_json:
        typer.echo(f"Registered {agent.name}", err=True)
    return agent


@app.command()
def send(
    target: Annotated[str, typer.Argument(help="Registered agent (id, name, URL) or agent URL.")],
    text: Annotated[str, typer.Argument(help="Message text.")],
    file: Annotated[
        list[Path] | None, typer.Option("--file", help="Attach a file as raw bytes.")
    ] = None,
    url: Annotated[list[str] | None, typer.Option("--url", help="Attach a file by URL.")] = None,
    data: Annotated[str | None, typer.Option(help="Attach a JSON data part.")] = None,
    stream: Annotated[bool, typer.Option("--stream/--no-stream")] = True,
    return_immediately: Annotated[bool, typer.Option("--return-immediately")] = False,
    accept: Annotated[
        list[str] | None, typer.Option("--accept", help="Accepted output media type.")
    ] = None,
    history_length: Annotated[int | None, typer.Option(min=0)] = None,
    extension: Annotated[
        list[str] | None, typer.Option("--extension", help="Activate an extension URI.")
    ] = None,
    metadata: Annotated[str | None, typer.Option(help="Message metadata as JSON.")] = None,
    reference_task: Annotated[
        list[str] | None, typer.Option("--reference-task", help="Referenced task id.")
    ] = None,
    context_id: Annotated[str | None, typer.Option()] = None,
    task_id: Annotated[str | None, typer.Option()] = None,
    interface: Annotated[str | None, typer.Option(help="Interface URL to use.")] = None,
    as_json: JsonFlag = False,
) -> None:
    """Send a message and print every resulting event (NDJSON with --json)."""
    meta = _parse_json(metadata, "--metadata")
    data_value = _parse_json(data, "--data")
    parts: list[AnyPartInput] = [TextPartInput(text=text)]
    for path in file or []:
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        parts.append(
            FilePartInput(
                raw_base64=base64.b64encode(path.read_bytes()).decode(),
                media_type=media_type,
                filename=path.name,
            )
        )
    parts.extend(FilePartInput(url=u) for u in url or [])
    if data is not None:
        parts.append(DataPartInput(data=data_value))
    options = SendOptions(
        stream=stream,
        return_immediately=return_immediately,
        accepted_output_modes=accept or [],
        history_length=history_length,
        extensions=extension or [],
        message_metadata=meta,
        reference_task_ids=reference_task or [],
        context_id=context_id,
        task_id=task_id,
        interface_url=interface,
    )

    async def go() -> ExitCode:
        async with Workbench.open(Settings()) as wb:
            agent = await _resolve_or_register(wb, target, as_json)
            conv = await wb.conversations.create(agent.id, origin="cli")
            code = ExitCode.OK
            printer = HumanPrinter()
            async for event in wb.conversations.send(conv.id, parts, options):
                if as_json:
                    print_json(event.model_dump(mode="json"))
                else:
                    for line in printer.feed(event):
                        typer.echo(line)
                if event.kind == "error":
                    code = exit_code_for(event.data["category"])
            if not as_json:
                for line in printer.finish():
                    typer.echo(line)
            return code

    code = _run(go())
    if code:
        raise typer.Exit(code)


@app.command()
def fixtures(
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = 9999,
    unsigned: Annotated[bool, typer.Option("--unsigned", help="Serve an unsigned card.")] = False,
) -> None:
    """Run the zoo reference agent until interrupted."""
    import uvicorn

    from a2a_workbench.fixtures.zoo import build_zoo_app

    base_url = f"http://{host}:{port}"
    typer.echo(f"Zoo agent at {base_url}", err=True)
    uvicorn.run(build_zoo_app(base_url, signed=not unsigned), host=host, port=port)


def main() -> None:
    """Run the CLI, mapping unexpected exceptions to exit code 6."""
    try:
        app()
    except SystemExit:
        raise
    except Exception as exc:
        typer.echo(f"internal error: {type(exc).__name__}: {exc}", err=True)
        sys.exit(ExitCode.INTERNAL)
