#!/usr/bin/env bash
# Prints the body of one version's section of a changelog (default CHANGELOG.md).
# Exits 1 when the section is missing or empty.
set -euo pipefail
version="${1:?usage: release-notes.sh <version> [changelog]}"
changelog="${2:-$(cd "$(dirname "$0")/.." && pwd)/CHANGELOG.md}"
notes="$(awk -v v="$version" '
  /^## / { inside = ($2 == v); next }
  inside { print }
' "$changelog" | sed -e '/./,$!d' | sed -e ':a' -e '/^\n*$/{$d;N;ba' -e '}')"
[ -n "$notes" ] || { echo "no notes for $version in $changelog" >&2; exit 1; }
printf '%s\n' "$notes"
