#!/usr/bin/env bash
# Builds the web UI into the Python package, then the wheel and sdist.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
(cd "$root/web" && pnpm install --frozen-lockfile && pnpm build)
rm -rf "$root/server/a2a_workbench/static"
cp -R "$root/web/dist" "$root/server/a2a_workbench/static"
if [ "${1:-}" != "--no-wheel" ]; then
  (cd "$root/server" && uv build)
fi
