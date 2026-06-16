#!/usr/bin/env bash
# integration_setup.sh — sample integration setup for a new project namespace
#
# Usage:
#   ./scripts/integration_setup.sh <project-id> [base-url]
#
# Example:
#   ./scripts/integration_setup.sh my-rag-app http://localhost:8000
#
# What this does:
#   1. Validates the project ID format
#   2. Registers the project via the API
#   3. Prints example SDK usage for the stack

set -euo pipefail

PROJECT_ID="${1:-}"
BASE_URL="${2:-http://localhost:8000}"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: $0 <project-id> [base-url]"
  echo "Example: $0 my-rag-app http://localhost:8000"
  exit 1
fi

# Validate project ID format
if ! echo "$PROJECT_ID" | grep -qE '^[a-z0-9][a-z0-9\-]{1,62}[a-z0-9]$'; then
  echo "ERROR: Invalid project ID '$PROJECT_ID'"
  echo "  Must be 3-64 characters, lowercase alphanumeric + dashes"
  echo "  Must start and end with alphanumeric character"
  exit 1
fi

echo ""
echo "=== Integration Setup: $PROJECT_ID ==="
echo ""

# 1. Check service health
echo "1. Checking service health..."
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/health" 2>/dev/null || echo "000")
if [[ "$HTTP_STATUS" != "200" ]]; then
  echo "   ERROR: Service not reachable at $BASE_URL (HTTP $HTTP_STATUS)"
  echo "   Ensure the service is running: systemctl start quartermaster"
  exit 1
fi
echo "   OK - service reachable"

# 2. Register the project
echo ""
echo "2. Registering project '$PROJECT_ID'..."
REGISTER_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/projects" \
  -H "Content-Type: application/json" \
  -d "{\"project_id\": \"${PROJECT_ID}\", \"name\": \"${PROJECT_ID}\", \"retention_profile\": \"standard\", \"deployment_profile\": \"standard\"}" \
  2>/dev/null)
HTTP_CODE=$(echo "$REGISTER_RESPONSE" | tail -1)
BODY=$(echo "$REGISTER_RESPONSE" | head -1)

if [[ "$HTTP_CODE" == "200" ]]; then
  echo "   OK - project registered"
elif [[ "$HTTP_CODE" == "409" ]]; then
  echo "   INFO - project already exists (skipping)"
else
  echo "   ERROR: Registration failed (HTTP $HTTP_CODE)"
  echo "   $BODY"
  exit 1
fi

# 3. Smoke test ingestion
echo ""
echo "3. Running ingestion smoke test..."
TEST_PAYLOAD=$(cat <<EOF
{
  "provider": "test",
  "model": "test-model",
  "workflow": "setup/smoke-test",
  "prompt_tokens": 1,
  "completion_tokens": 1,
  "total_tokens": 2,
  "latency_ms": 1.0,
  "success": true,
  "request_kind": "completion",
  "project_id": "${PROJECT_ID}",
  "schema_version": "1.0"
}
EOF
)

SMOKE_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/llm/events" \
  -H "Content-Type: application/json" \
  -d "$TEST_PAYLOAD" 2>/dev/null)
SMOKE_CODE=$(echo "$SMOKE_RESPONSE" | tail -1)

if [[ "$SMOKE_CODE" == "200" ]]; then
  echo "   OK - ingestion working"
else
  echo "   ERROR: Smoke test failed (HTTP $SMOKE_CODE)"
  exit 1
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Project '$PROJECT_ID' is ready for ingestion."
echo ""
echo "Example SDK usage:"
echo ""
echo "  from sdk.python.client import OperationalMemoryClient"
echo "  from sdk.python.helpers import build_event"
echo ""
echo "  client = OperationalMemoryClient("
echo "      base_url='${BASE_URL}',"
echo "      project_id='${PROJECT_ID}',"
echo "  )"
echo ""
echo "  event = build_event("
echo "      provider='anthropic',"
echo "      model='claude-sonnet-4-6',"
echo "      workflow='my-workflow',"
echo "      prompt_tokens=1200,"
echo "      completion_tokens=350,"
echo "      latency_ms=2800.0,"
echo "  )"
echo "  client.send_event(event)"
echo ""
echo "Run integration check:"
echo "  python -m cli.main integration-check --project ${PROJECT_ID} --url ${BASE_URL}"
echo ""
