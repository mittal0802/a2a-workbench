# Contributing

## Setup

```bash
git config core.hooksPath .githooks      # enforces commit identity and message rules
cd server && uv sync
cd ../web && pnpm install
```

## Rules

1. **Only what the A2A protocol officially supports.** All A2A traffic goes through the official `a2a-sdk`. No invented fields, methods, metadata conventions or extensions. Gaps go to [`docs/upstream-gaps.md`](docs/upstream-gaps.md) as upstream proposals, never local workarounds.
2. **Docstrings describe the function itself**: purpose, parameters, return value, errors and side effects. Never where or how it is used.
3. **Every feature ships in core first, then in every surface** (web UI, CLI, MCP), each with tests. `a2a_workbench.core` never imports web, CLI or MCP code.
4. **Tests first.** Backend tests run against the agent zoo (`a2a_workbench/fixtures`), built with the official SDK server.

## Commits

Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`), small and focused.
