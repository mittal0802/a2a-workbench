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
from a2a_workbench.core.errors import AgentCallError
from a2a_workbench.core.registry.service import AgentExistsError, AgentNotFoundError, AgentOut
from a2a_workbench.core.workbench import Workbench

app = typer.Typer(
    no_args_is_help=True,
    help="Debug, test and conformance-check A2A agents.",
    pretty_exceptions_enable=False,
)
agents_app = typer.Typer(no_args_is_help=True, help="Manage registered agents.")
app.add_typer(agents_app, name="agents")
tasks_app = typer.Typer(no_args_is_help=True, help="Get, list, cancel and resubscribe to tasks.")
app.add_typer(tasks_app, name="tasks")
faults_app = typer.Typer(no_args_is_help=True, help="Fault profiles for failure injection.")
app.add_typer(faults_app, name="faults")
auth_app = typer.Typer(no_args_is_help=True, help="Sign in to agents and check enforcement.")
app.add_typer(auth_app, name="auth")

FaultsOpt = Annotated[
    str | None,
    typer.Option("--faults", help="Inject failures: a preset name or a profile JSON file."),
]


def _faults(spec: str | None) -> Any:
    if spec is None:
        return None
    from a2a_workbench.core.faults.injector import FaultInjector
    from a2a_workbench.core.faults.profile import load_profile

    try:
        return FaultInjector(load_profile(spec))
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(ExitCode.USAGE) from exc


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
    from a2a_workbench.api.logs import log_config

    settings = Settings()
    bind_host, bind_port = host or settings.host, port or settings.port
    if open_browser:
        webbrowser.open(f"http://{bind_host}:{bind_port}")
    uvicorn.run(
        create_app(settings),
        host=bind_host,
        port=bind_port,
        log_level="info",
        log_config=log_config(),
    )


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


def _print_extended(out: Any, as_json: bool) -> None:
    if as_json:
        print_json(out.model_dump(mode="json"))
        return
    if not out.diff:
        typer.echo("The extended card is identical to the public card.")
    for d in out.diff:
        typer.echo(f"  {d['change']} {d['path']}")


@app.command()
def card(
    target: Annotated[str, typer.Argument(help="Agent URL, card URL or registered agent.")],
    extended: Annotated[
        bool, typer.Option("--extended", help="Fetch the extended card and show differences.")
    ] = False,
    as_json: JsonFlag = False,
) -> None:
    """Fetch an agent card and verify its signature (or fetch its extended card)."""

    async def go() -> None:
        async with Workbench.open(Settings()) as wb:
            url, card_path, agent_id = target, None, None
            try:
                agent = await wb.agents.resolve(target)
                url, card_path, agent_id = agent.base_url, agent.card_path, agent.id
            except AgentNotFoundError:
                pass
            if extended:
                try:
                    out = (
                        await wb.agents.get_extended_card(agent_id)
                        if agent_id
                        else await wb.agents.extended_card_for_url(url, card_path)
                    )
                except CardFetchError as exc:
                    _card_failure(exc, as_json)
                except AgentCallError as exc:
                    _fail(exc.classified["category"], str(exc), as_json)
                _print_extended(out, as_json)
                return
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
    skill: Annotated[
        str | None,
        typer.Option(
            help="Apply this skill's security requirements from the card (A2A messages carry "
            "no skill; the agent still chooses how to handle the request)."
        ),
    ] = None,
    faults: FaultsOpt = None,
    as_json: JsonFlag = False,
) -> None:
    """Send a message and print every resulting event (NDJSON with --json)."""
    profile = _faults(faults)
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
        faults=profile.profile if profile else None,
        skill_id=skill,
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
                if event.kind in ("error", "connection_lost"):
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
    grpc_port: Annotated[
        int | None, typer.Option(help="gRPC port (default: HTTP port + 1).")
    ] = None,
    no_grpc: Annotated[bool, typer.Option("--no-grpc", help="Do not serve gRPC.")] = False,
    legacy: Annotated[bool, typer.Option("--legacy", help="Speak A2A 0.3 instead of 1.0.")] = False,
    auth: Annotated[
        str,
        typer.Option(
            help="Require sign-in: apikey-header, apikey-query, apikey-cookie, basic, bearer, "
            "and, oauth, oidc."
        ),
    ] = "none",
    idp_port: Annotated[
        int | None,
        typer.Option(help="Mock identity provider port for oauth/oidc (default: HTTP port + 3)."),
    ] = None,
) -> None:
    """Run the zoo reference agent until interrupted."""
    import uvicorn

    from a2a_workbench.fixtures.zoo import build_zoo_app

    base_url = f"http://{host}:{port}"
    grpc = None if no_grpc else (grpc_port or port + 1)
    typer.echo(
        f"Zoo agent at {base_url}"
        + (f" (gRPC on {host}:{grpc})" if grpc else "")
        + (" speaking A2A 0.3" if legacy else ""),
        err=True,
    )
    if auth != "none":
        from a2a_workbench.fixtures.auth import ZOO_SECRETS

        typer.echo(f"Sign-in required ({auth}); test credentials: {ZOO_SECRETS}", err=True)
    idp = None
    if auth in ("oauth", "oidc"):
        from a2a_workbench.fixtures.idp import IDP_CLIENT, IdpServer

        idp_server = IdpServer(port=idp_port or port + 3)
        idp_server.start()
        idp = idp_server.idp
        typer.echo(
            f"Mock identity provider at {idp.issuer}; client {IDP_CLIENT['id']} / "
            f"{IDP_CLIENT['secret']}",
            err=True,
        )
    app_ = build_zoo_app(
        base_url, signed=not unsigned, grpc_port=grpc, legacy=legacy, auth=auth, idp=idp
    )
    uvicorn.run(app_, host=host, port=port)


async def _agent_id(wb: Workbench, target: str, as_json: bool) -> str:
    return (await _resolve_or_register(wb, target, as_json)).id


def _task_call_failed(exc: AgentCallError, as_json: bool) -> NoReturn:
    c = exc.classified
    if as_json:
        print_json({"error": c})
    else:
        typer.echo(
            f"error ({c['category']}): {c.get('reason') or ''} {c['message']}".strip(), err=True
        )
    raise typer.Exit(exit_code_for(c["category"]))


def _task_line(t: dict[str, Any]) -> str:
    history = t.get("history") or []
    first = next(
        (
            p.get("text")
            for m in history
            if m.get("role") == "ROLE_USER"
            for p in m.get("parts", [])
            if p.get("text")
        ),
        "",
    )
    updated = t.get("status", {}).get("timestamp", "")
    return f"{t['id']}  {t['state']:<15} {updated:<27} {first[:50]}"


@tasks_app.command("list")
def tasks_list(
    target: Annotated[str, typer.Argument(help="Registered agent or agent URL.")],
    context_id: Annotated[str | None, typer.Option()] = None,
    status: Annotated[str | None, typer.Option(help="e.g. working, completed")] = None,
    updated_after: Annotated[
        str | None, typer.Option(help="ISO-8601 time (status_timestamp_after).")
    ] = None,
    include_artifacts: Annotated[
        bool | None, typer.Option("--include-artifacts/--no-include-artifacts")
    ] = None,
    history_length: Annotated[int | None, typer.Option(min=0)] = None,
    page_size: Annotated[int | None, typer.Option(min=1)] = None,
    page_token: Annotated[str | None, typer.Option()] = None,
    all_pages: Annotated[
        bool, typer.Option("--all", help="Follow next_page_token to the end.")
    ] = False,
    faults: FaultsOpt = None,
    as_json: JsonFlag = False,
) -> None:
    """List tasks with every ListTasks filter."""
    profile = _faults(faults)
    from datetime import datetime

    from pydantic import ValidationError

    from a2a_workbench.core.tasks.service import ListTasksFilter

    try:
        f = ListTasksFilter(
            context_id=context_id,
            status=status,
            status_timestamp_after=datetime.fromisoformat(updated_after) if updated_after else None,
            include_artifacts=include_artifacts,
            history_length=history_length,
            page_size=page_size,
            page_token=page_token,
        )
    except (ValueError, ValidationError) as exc:
        typer.echo(f"invalid filter: {exc}", err=True)
        raise typer.Exit(ExitCode.USAGE) from exc

    async def go() -> dict[str, Any]:
        async with Workbench.open(Settings()) as wb:
            agent_id = await _agent_id(wb, target, as_json)
            try:
                page = await wb.tasks.list(agent_id, f, faults=profile)
                tasks = list(page["tasks"])
                while all_pages and page.get("next_page_token"):
                    page = await wb.tasks.list(
                        agent_id,
                        f.model_copy(update={"page_token": page["next_page_token"]}),
                        faults=profile,
                    )
                    tasks += page["tasks"]
            except AgentCallError as exc:
                _task_call_failed(exc, as_json)
            return {**page, "tasks": tasks}

    result = _run(go())
    if as_json:
        print_json(result)
        return
    for t in result["tasks"]:
        typer.echo(_task_line(t))
    typer.echo(f"{len(result['tasks'])} of {result.get('total_size')} tasks", err=True)
    if result.get("next_page_token") and not all_pages:
        typer.echo(f"next page: --page-token {result['next_page_token']}", err=True)


@tasks_app.command("get")
def tasks_get(
    target: Annotated[str, typer.Argument(help="Registered agent or agent URL.")],
    task_id: str,
    history_length: Annotated[int | None, typer.Option(min=0)] = None,
    faults: FaultsOpt = None,
    as_json: JsonFlag = False,
) -> None:
    """Get one task (GetTask)."""
    profile = _faults(faults)

    async def go() -> dict[str, Any]:
        async with Workbench.open(Settings()) as wb:
            try:
                return await wb.tasks.get(
                    await _agent_id(wb, target, as_json),
                    task_id,
                    history_length=history_length,
                    faults=profile,
                )
            except AgentCallError as exc:
                _task_call_failed(exc, as_json)

    task = _run(go())
    if as_json:
        print_json(task)
    else:
        typer.echo(_task_line(task))
        for artifact in task.get("artifacts", []):
            typer.echo(f"  artifact {artifact.get('name') or artifact.get('artifactId')}")


@tasks_app.command("cancel")
def tasks_cancel(
    target: Annotated[str, typer.Argument(help="Registered agent or agent URL.")],
    task_id: str,
    metadata: Annotated[str | None, typer.Option(help="CancelTask metadata as JSON.")] = None,
    faults: FaultsOpt = None,
    as_json: JsonFlag = False,
) -> None:
    """Cancel a task (CancelTask)."""
    meta = _parse_json(metadata, "--metadata")
    profile = _faults(faults)

    async def go() -> dict[str, Any]:
        async with Workbench.open(Settings()) as wb:
            try:
                return await wb.tasks.cancel(
                    await _agent_id(wb, target, as_json), task_id, metadata=meta, faults=profile
                )
            except AgentCallError as exc:
                _task_call_failed(exc, as_json)

    task = _run(go())
    print_json(task) if as_json else typer.echo(_task_line(task))


@tasks_app.command("subscribe")
def tasks_subscribe(
    target: Annotated[str, typer.Argument(help="Registered agent or agent URL.")],
    task_id: str,
    faults: FaultsOpt = None,
    as_json: JsonFlag = False,
) -> None:
    """Resubscribe to a task's event stream (SubscribeToTask); NDJSON with --json."""
    profile = _faults(faults)

    async def go() -> None:
        async with Workbench.open(Settings()) as wb:
            agent_id = await _agent_id(wb, target, as_json)
            try:
                async for event in wb.tasks.subscribe(agent_id, task_id, faults=profile):
                    if as_json:
                        print_json(event)
                    else:
                        typer.echo(
                            f"{event['kind']}{': ' + event['state'] if event['state'] else ''}"
                        )
            except AgentCallError as exc:
                _task_call_failed(exc, as_json)

    _run(go())


@app.command()
def mcp(
    transport: Annotated[
        str, typer.Option(help="stdio (for Claude Code / Desktop) or streamable-http.")
    ] = "stdio",
    host: Annotated[str, typer.Option(help="Bind host for streamable-http.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port for streamable-http.")] = 8765,
) -> None:
    """Run the MCP server so AI agents (e.g. Claude Code) can test A2A agents."""
    if transport not in ("stdio", "streamable-http"):
        typer.echo("--transport must be stdio or streamable-http", err=True)
        raise typer.Exit(ExitCode.USAGE)
    from a2a_workbench.mcp.server import build_mcp_server

    async def go() -> None:
        async with Workbench.open(Settings()) as wb:
            server = build_mcp_server(wb)
            if transport == "stdio":
                await server.run_stdio_async()
            else:
                await server.run_streamable_http_async(host=host, port=port)

    _run(go())


@faults_app.command("presets")
def faults_presets(as_json: JsonFlag = False) -> None:
    """List the built-in fault presets."""
    from a2a_workbench.core.faults.profile import PRESETS

    if as_json:
        print_json([p.model_dump(mode="json") for p in PRESETS.values()])
        return
    for p in PRESETS.values():
        typer.echo(f"{p.name:<14} {p.description}")


@faults_app.command("validate")
def faults_validate(path: Annotated[Path, typer.Argument(help="Profile JSON file.")]) -> None:
    """Check that a fault profile file is valid."""
    injector = _faults(str(path))
    typer.echo(f"valid: {len(injector.profile.rules)} rule(s)")


def _secret(value: str | None) -> str | None:
    """Return ``value``, or one line read from standard input when it is ``-``."""
    if value == "-":
        return sys.stdin.readline().rstrip("\r\n")
    return value


def _auth_failed(exc: Exception, as_json: bool) -> NoReturn:
    from a2a_workbench.core.auth.service import CredentialError

    if isinstance(exc, AgentCallError):
        _task_call_failed(exc, as_json)
    if isinstance(exc, CredentialError):
        _fail("workbench", str(exc), as_json, ExitCode.USAGE)
    raise exc


@auth_app.command("status")
def auth_status(
    target: Annotated[str, typer.Argument(help="Registered agent or agent URL.")],
    as_json: JsonFlag = False,
) -> None:
    """Show the agent's security schemes and whether you are signed in."""
    from a2a_workbench.core.a2a_json import card_from_json

    async def go() -> Any:
        async with Workbench.open(Settings()) as wb:
            agent = await _resolve_or_register(wb, target, as_json)
            row = await wb.agents.row(agent.id)
            return await wb.auth.overview(agent.id, card_from_json(row.card))

    overview = _run(go())
    if as_json:
        print_json(overview.model_dump(mode="json"))
        return
    typer.echo(f"status: {overview.status}")
    for scheme in overview.schemes:
        cred = scheme.credential.preview if scheme.credential else "not set"
        flows = f" [{', '.join(scheme.flows)}]" if scheme.flows else ""
        typer.echo(f"  {scheme.name:<16} {scheme.label}{flows}: {cred}")
    if overview.missing:
        typer.echo(f"missing: {', '.join(overview.missing)}")


@auth_app.command("set")
def auth_set(
    target: Annotated[str, typer.Argument(help="Registered agent or agent URL.")],
    scheme: Annotated[str, typer.Argument(help="Security scheme name from the card.")],
    api_key: Annotated[
        str | None, typer.Option(envvar="A2AW_API_KEY", help="API key value ('-' reads stdin).")
    ] = None,
    username: Annotated[str | None, typer.Option()] = None,
    password: Annotated[
        str | None, typer.Option(envvar="A2AW_PASSWORD", help="Password ('-' reads stdin).")
    ] = None,
    token: Annotated[
        str | None, typer.Option(envvar="A2AW_TOKEN", help="Bearer token ('-' reads stdin).")
    ] = None,
    access_token: Annotated[
        str | None,
        typer.Option(
            envvar="A2AW_ACCESS_TOKEN",
            help="OAuth access token you already have ('-' reads stdin).",
        ),
    ] = None,
    cert: Annotated[Path | None, typer.Option(help="Client certificate PEM file.")] = None,
    key: Annotated[Path | None, typer.Option(help="Client private key PEM file.")] = None,
    ca: Annotated[Path | None, typer.Option(help="CA PEM file to trust.")] = None,
    as_json: JsonFlag = False,
) -> None:
    """Store a credential for one of the agent's security schemes."""
    from a2a_workbench.core.a2a_json import card_from_json

    api_key, password, token, access_token = (
        _secret(v) for v in (api_key, password, token, access_token)
    )

    async def go() -> Any:
        from a2a_workbench.core.auth.service import credential_values

        async with Workbench.open(Settings()) as wb:
            agent = await _resolve_or_register(wb, target, as_json)
            card = card_from_json((await wb.agents.row(agent.id)).card)
            try:
                kind, secret = credential_values(
                    card,
                    scheme,
                    api_key=api_key,
                    username=username,
                    password=password,
                    token=token,
                    access_token=access_token,
                    cert_pem=cert.read_text() if cert else None,
                    key_pem=key.read_text() if key else None,
                    ca_pem=ca.read_text() if ca else None,
                )
                return await wb.auth.set_credential(agent.id, card, scheme, kind, secret)
            except Exception as exc:
                _auth_failed(exc, as_json)

    info = _run(go())
    print_json(info.model_dump(mode="json")) if as_json else typer.echo(
        f"Saved {scheme}: {info.preview}"
    )


@auth_app.command("login")
def auth_login(
    target: Annotated[str, typer.Argument(help="Registered agent or agent URL.")],
    scheme: Annotated[str, typer.Argument(help="OAuth2 / OpenID Connect scheme name.")],
    client_id: Annotated[str, typer.Option(help="OAuth client id.")],
    client_secret: Annotated[
        str | None,
        typer.Option(envvar="A2AW_CLIENT_SECRET", help="OAuth client secret ('-' reads stdin)."),
    ] = None,
    scope: Annotated[list[str] | None, typer.Option("--scope", help="Scope to request.")] = None,
    username: Annotated[str | None, typer.Option(help="For the password flow.")] = None,
    password: Annotated[
        str | None,
        typer.Option(envvar="A2AW_PASSWORD", help="For the password flow ('-' reads stdin)."),
    ] = None,
    auth_method: Annotated[
        str, typer.Option(help="client_secret_post or client_secret_basic.")
    ] = "client_secret_post",
    redirect_port: Annotated[int, typer.Option(help="Local port for the browser callback.")] = 8765,
    no_browser: Annotated[bool, typer.Option("--no-browser", help="Print the URL only.")] = False,
    url_file: Annotated[Path | None, typer.Option(hidden=True)] = None,
    timeout: Annotated[
        float, typer.Option(help="Seconds to wait for browser/device sign-in.")
    ] = 300,
    as_json: JsonFlag = False,
) -> None:
    """Sign in with the scheme's OAuth flow (direct, device code or browser)."""
    from a2a_workbench.cli.oauth_callback import CallbackServer
    from a2a_workbench.core.a2a_json import card_from_json

    client_secret, password = _secret(client_secret), _secret(password)

    async def go() -> Any:
        async with Workbench.open(Settings()) as wb:
            agent = await _resolve_or_register(wb, target, as_json)
            card = card_from_json((await wb.agents.row(agent.id)).card)
            try:
                flow = wb.auth.flow_for(card, scheme)
                if flow in ("client_credentials", "password"):
                    return await wb.auth.sign_in(
                        agent.id,
                        scheme,
                        flow=flow,
                        client_id=client_id,
                        client_secret=client_secret,
                        scopes=scope or [],
                        auth_method=auth_method,
                        username=username,
                        password=password,
                        card=card,
                    )
                if flow == "device_code":
                    device = await wb.auth.start_device_flow(
                        agent.id,
                        scheme,
                        client_id=client_id,
                        client_secret=client_secret,
                        scopes=scope or [],
                        card=card,
                    )
                    typer.echo(
                        f"To sign in, open {device.verification_uri} "
                        f"and enter code: {device.user_code}",
                        err=True,
                    )
                    deadline = asyncio.get_running_loop().time() + timeout
                    while asyncio.get_running_loop().time() < deadline:
                        if await wb.auth.poll_device_flow(device.flow_id) == "signed_in":
                            return await wb.credentials.list(agent.id)
                        await asyncio.sleep(max(device.interval, 0.2))
                    _fail("auth", "device sign-in timed out", as_json, ExitCode.AUTH)
                with CallbackServer(redirect_port) as callback:
                    start = await wb.auth.start_browser_flow(
                        agent.id,
                        scheme,
                        client_id=client_id,
                        client_secret=client_secret,
                        scopes=scope or [],
                        redirect_uri=callback.redirect_uri,
                        card=card,
                    )
                    typer.echo(f"Open this URL to sign in:\n{start.authorize_url}", err=True)
                    if url_file:
                        url_file.write_text(start.authorize_url)
                    if not no_browser:
                        webbrowser.open(start.authorize_url)
                    params = await asyncio.to_thread(callback.wait, timeout)
                if params is None:
                    _fail("auth", "browser sign-in timed out", as_json, ExitCode.AUTH)
                return await wb.auth.finish_browser_flow(
                    state=params.get("state", ""),
                    code=params.get("code"),
                    access_token=params.get("access_token"),
                    expires_in=int(params["expires_in"]) if params.get("expires_in") else None,
                    scope=params.get("scope"),
                    error=params.get("error"),
                    error_description=params.get("error_description"),
                )
            except Exception as exc:
                _auth_failed(exc, as_json)

    result = _run(go())
    if isinstance(result, list):
        result = next(i for i in result if i.scheme_name == scheme)
    if as_json:
        print_json(result.model_dump(mode="json"))
    else:
        typer.echo(f"Signed in to {scheme}: {result.preview}")


@auth_app.command("logout")
def auth_logout(
    target: Annotated[str, typer.Argument(help="Registered agent or agent URL.")],
    scheme: Annotated[str, typer.Argument(help="Security scheme name.")],
) -> None:
    """Remove the stored credential for a scheme."""

    async def go() -> None:
        async with Workbench.open(Settings()) as wb:
            agent = await _resolve_or_register(wb, target, False)
            await wb.credentials.delete(agent.id, scheme)

    _run(go())
    typer.echo(f"Signed out of {scheme}")


@auth_app.command("probe")
def auth_probe(
    target: Annotated[str, typer.Argument(help="Registered agent or agent URL.")],
    as_json: JsonFlag = False,
) -> None:
    """Check the agent enforces its declared authentication (exit 1 if a check fails)."""
    from a2a_workbench.core.a2a_json import card_from_json

    async def go() -> list[Any]:
        async with Workbench.open(Settings()) as wb:
            agent = await _resolve_or_register(wb, target, as_json)
            row = await wb.agents.row(agent.id)
            return await wb.auth.probe(
                agent.id, card_from_json(row.card), row.selected_interface_url
            )

    results = _run(go())
    if as_json:
        print_json([r.model_dump() for r in results])
    else:
        for r in results:
            typer.echo(f"{r.outcome:<15} {r.title} — {r.detail}")
    if any(r.outcome == "fail" for r in results):
        raise typer.Exit(ExitCode.CHECKS_FAILED)


def main() -> None:
    """Run the CLI, mapping unexpected exceptions to exit code 6."""
    try:
        app()
    except SystemExit:
        raise
    except Exception as exc:
        typer.echo(f"internal error: {type(exc).__name__}: {exc}", err=True)
        sys.exit(ExitCode.INTERNAL)
