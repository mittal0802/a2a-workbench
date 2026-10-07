# A2A Workbench

Open-source developer tool (Apache-2.0) for connecting to, debugging and
conformance-testing any A2A agent, through a web UI, a CLI and an MCP server
that share one core library.

- Design spec: `docs/superpowers/specs/2026-10-07-a2a-workbench-design.md`
- Approved UI: `docs/design/ui-mockup.html`

## Hard rules

These are non-negotiable. If a task conflicts with one of them, stop and ask
instead of working around it.

### 1. Only what the A2A protocol officially supports

- Implement only features, fields, methods, states, errors and behaviours
  defined in the official A2A specification (a2a-protocol.org) and
  `a2aproject/A2A`. Do not invent protocol fields, methods, headers, metadata
  conventions, part types or extensions, and do not add "helpful" non-spec
  behaviour to protocol traffic.
- All A2A traffic goes through the official SDK `a2a-sdk`
  (`a2aproject/a2a-python`). Never hand-build, hand-parse or re-implement A2A
  requests, responses, types, serialization or transports.
- Supported protocol versions are those the official SDK supports (v1.0
  native, v0.3 through `a2a.compat.v0_3`). Do not add support for other
  versions by any other means.
- Health checks enforce only what the spec says. Each check cites its spec
  section, and "MUST" vs. "SHOULD" in the spec decides fail vs. warn. A
  feature the agent does not declare is reported as not supported, never as
  a failure.
- If something we need is missing from the SDK or the spec, do **not**
  implement it locally. Record it in `docs/upstream-gaps.md` (what is
  missing, why we need it, a proposed API) for an upstream PR or proposal.
  Nothing is opened upstream without the maintainer's approval.
- Allowed, because they are not protocol features: client-side UX (chat,
  Inspect, Assistant), storage, and fault injection *beneath* the SDK through
  `ClientConfig.httpx_client` / `grpc_channel_factory`. Fault injection
  disturbs connections and bytes only; it never alters what the SDK sends.

### 2. No AI attribution in git history

- Never add `Co-Authored-By: Claude …`, "Generated with Claude Code",
  "committed by Claude", or any other AI or tool attribution to commit
  messages, PR titles or descriptions, tags, release notes or code comments.
- Commit with the repository's configured personal git identity. Never
  change `user.name` / `user.email`, and never pass `--author`.
- This repo lives under the personal GitHub account `mittal0802`
  (`github.com/mittal0802/a2a-workbench`). The only allowed commit identity is
  `Keshav Mittal <mittalkeshav41@gmail.com>`. Never push to or reference any
  work or organization account or remote.
- `.githooks/` enforces both rules; keep `git config core.hooksPath .githooks`
  set and never bypass the hooks with `--no-verify`.

### 3. Docstrings describe the function, not its callers

- A docstring states what the function or class does: its purpose, its
  parameters, what it returns or yields, what it raises, and notable
  behaviour such as side effects, ordering or idempotency.
- Never describe where or how it is used ("used by the chat tab", "called
  from the CLI", "this is used there like this"), which callers exist, or
  call-site examples tied to other modules.
- The same applies to class, module and inline comments: explain *what* and
  *why* locally, never *who uses it*.

Good:
```python
def assemble_artifact(chunks: list[TaskArtifactUpdateEvent]) -> Artifact:
    """Merge streamed artifact chunks into one artifact.

    Applies ``append`` semantics in arrival order and requires the final
    chunk to have ``last_chunk`` set.

    Raises:
        IncompleteArtifactError: if no chunk has ``last_chunk`` set.
    """
```

Bad: `"""Merges chunks. Used by ConversationService and the CLI send command."""`

## Architecture rules

- `a2a_workbench.core` has no FastAPI, web, Typer or MCP imports. `api/`,
  `cli/` and `mcp/` are thin layers over core.
- Every feature ships in core first, then in all surfaces: web UI, CLI
  (`--json` / NDJSON output, stable exit codes, never interactive without a
  TTY) and MCP tools. A feature is not done until every surface has it and
  each has tests.
- Secrets are never logged, are redacted in recorded exchanges, and are
  stored only through the vault.
- Tests run against the agent zoo in `fixtures/`, which is built with the
  official SDK server. Each health check has a `broken-*` fixture proving it
  detects the violation.

## Workflow

- Follow the phased plan in the spec (§12). Each phase has its own plan in
  `docs/superpowers/plans/`.
- Test-driven: write the failing test first.
- Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`,
  `chore:`), with small, focused commits.
