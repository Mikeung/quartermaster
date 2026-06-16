#!/usr/bin/env bash
# ingestion_smoke.sh — run a quick ingestion smoke test against the service
#
# Sends a minimal synthetic event and verifies:
#   1. Service is reachable
#   2. Event is accepted (HTTP 200)
#   3. Privacy gate rejects forbidden fields (HTTP 422)
#   4. Storage endpoint is queryable
#
# Usage:
#   ./scripts/ingestion_smoke.sh [base-url] [project-id]
#
# Example:
#   ./scripts/ingestion_smoke.sh http://localhost:8000 my-app

set -euo pipefail

BASE_URL="${1:-http://localhost:8000}"
PROJECT_ID="${2:-smoke-test}"
PASS=0
FAIL=0

ok()   { echo "  [OK]   $*"; ((PASS++)); }
fail() { echo "  [FAIL] $*"; ((FAIL++)); }

echo ""
echo "=== Ingestion Smoke Test ==="
echo "  Service:  $BASE_URL"
echo "  Project:  $PROJECT_ID"
echo ""

# 1. Health check
echo "1. Health..."
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/health" 2>/dev/null || echo "000")
if [[ "$STATUS" == "200" ]]; then
  ok "Service healthy (HTTP $STATUS)"
else
  fail "Health check failed (HTTP $STATUS)"
  echo ""
  echo "Aborting — service not reachable at $BASE_URL"
  exit 1
fi

# 2. Valid event accepted
echo "2. Valid event ingestion..."
VALID_PAYLOAD=$(cat <<EOF
{
  "provider": "smoke-test",
  "model": "smoke-model",
  "workflow": "smoke-test/ingestion-check",
  "prompt_tokens": 5,
  "completion_tokens": 3,
  "total_tokens": 8,
  "latency_ms": 50.0,
  "success": true,
  "request_kind": "completion",
  "project_id": "${PROJECT_ID}",
  "schema_version": "1.0"
}
EOF
)
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE_URL}/llm/events" \
  -H "Content-Type: application/json" -d "$VALID_PAYLOAD" 2>/dev/null || echo "000")
if [[ "$STATUS" == "200" ]]; then
  ok "Valid event accepted (HTTP $STATUS)"
else
  fail "Valid event rejected unexpectedly (HTTP $STATUS)"
fi

# 3. Privacy gate — forbidden field must be rejected
echo "3. Privacy gate..."
FORBIDDEN_PAYLOAD=$(cat <<EOF
{
  "provider": "smoke-test",
  "model": "smoke-model",
  "workflow": "smoke-test/privacy-check",
  "prompt_tokens": 1,
  "completion_tokens": 1,
  "total_tokens": 2,
  "latency_ms": 1.0,
  "success": true,
  "prompt": "This must be rejected",
  "schema_version": "1.0"
}
EOF
)
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE_URL}/llm/events" \
  -H "Content-Type: application/json" -d "$FORBIDDEN_PAYLOAD" 2>/dev/null || echo "000")
if [[ "$STATUS" == "422" ]]; then
  ok "Privacy gate active — forbidden field rejected (HTTP $STATUS)"
else
  fail "Privacy gate may be inactive — forbidden field got HTTP $STATUS (expected 422)"
fi

# 4. Storage endpoint queryable
echo "4. Storage query..."
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/llm/storage" 2>/dev/null || echo "000")
if [[ "$STATUS" == "200" ]]; then
  ok "Storage endpoint queryable (HTTP $STATUS)"
else
  fail "Storage endpoint returned HTTP $STATUS"
fi

# 5. Projects endpoint queryable
echo "5. Projects endpoint..."
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/projects" 2>/dev/null || echo "000")
if [[ "$STATUS" == "200" ]]; then
  ok "Projects endpoint queryable (HTTP $STATUS)"
else
  fail "Projects endpoint returned HTTP $STATUS"
fi

echo ""
echo "--- Summary ---"
echo "  Passed: $PASS / $((PASS + FAIL))"
echo ""

if [[ $FAIL -gt 0 ]]; then
  echo "$FAIL smoke test(s) failed. Review service logs: journalctl -u quartermaster -n 50"
  exit 1
else
  echo "All smoke tests passed. Ingestion pipeline appears operational."
  exit 0
fi
