#!/usr/bin/env bash
# Fetch the LSPatch CLI jar into .tools/lspatch/ so the LSPatch pipeline
# can run. lspatch.jar is ~11 MB and not checked into git.
#
# Usage:    scripts/fetch_lspatch.sh [version]
#           default version is v0.8 (latest as of 2026-03)
set -euo pipefail

VERSION="${1:-v0.8}"
URL="https://github.com/JingMatrix/LSPatch/releases/download/${VERSION}/lspatch.jar"
DEST_DIR="$(cd "$(dirname "$0")/.." && pwd)/.tools/lspatch"
DEST="${DEST_DIR}/lspatch.jar"

mkdir -p "$DEST_DIR"
echo "fetching ${URL}"
echo "      → ${DEST}"
curl -L --fail --silent --show-error --output "$DEST" "$URL"
SIZE=$(wc -c < "$DEST" | tr -d ' ')
echo "downloaded ${SIZE} bytes"
if [ "$SIZE" -lt 1000000 ]; then
  echo "ERROR: jar too small — likely a redirect HTML, not the actual jar"
  exit 1
fi
echo "✓ lspatch.jar ready at $DEST"
