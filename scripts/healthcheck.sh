#!/usr/bin/env bash
# healthcheck.sh — check whether the running server is healthy
#
# Usage:
#   ./scripts/healthcheck.sh [host] [port]
#
# Defaults: localhost:8000
# Exit codes:
#   0 — healthy
#   1 — unhealthy or unreachable

set -euo pipefail

HOST="${1:-localhost}"
PORT="${2:-8000}"
BASE_URL="http://${HOST}:${PORT}"

die() { echo "[healthcheck] FAIL: $*" >&2; exit 1; }
ok() { echo "[healthcheck] OK: $*"; }

# Check /health endpoint
RESPONSE=$(curl -sf --max-time 5 "${BASE_URL}/health" 2>/dev/null) || \
    die "Server unreachable at ${BASE_URL}/health"

STATUS=$(echo "${RESPONSE}" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null || echo "unknown")

if [[ "${STATUS}" == "ok" || "${STATUS}" == "healthy" ]]; then
    ok "Server is healthy at ${BASE_URL} (status: ${STATUS})"
    exit 0
else
    die "Server returned status '${STATUS}' — check logs"
fi
