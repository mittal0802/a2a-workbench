#!/usr/bin/env bash
# Runs the zoo agent on :9999, the API on :8484 and the Vite dev server on :5173.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
trap 'kill 0' EXIT
(cd "$root/server" && uv run a2a-workbench fixtures --port 9999) &
(cd "$root/server" && uv run a2a-workbench serve --port 8484) &
(cd "$root/web" && pnpm dev) &
wait
