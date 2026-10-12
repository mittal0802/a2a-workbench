#!/usr/bin/env bash
# Exits 0 when the tag (e.g. v1.0.0) matches the package version.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
version="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$root/server/a2a_workbench/__init__.py")"
[ "${1:-}" = "v$version" ] || { echo "tag ${1:-<none>} does not match version $version" >&2; exit 1; }
