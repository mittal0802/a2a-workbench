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

## Docs

The site is built with MkDocs Material from `docs/` (`mkdocs.yml`). The pages under `docs/reference/` are generated from the code: after changing a check, a CLI command or a setting, run `cd server && uv run python ../scripts/gen_docs.py`. CI fails when they are stale.

## Releasing

1. Set `__version__` in `server/a2a_workbench/__init__.py` and add a `## <version>` section to `CHANGELOG.md`.
2. Merge to `main` with CI green.
3. Tag and push: `git tag -a v<version> -m "v<version>" && git push origin v<version>`.

The `Release` workflow checks the tag against the version, runs CI, builds the wheel and sdist with the web UI inside, smoke-installs the wheel, publishes to PyPI (trusted publishing, no tokens), pushes the multi-arch image to `ghcr.io/mittal0802/a2a-workbench`, and creates the GitHub release from the changelog section.
