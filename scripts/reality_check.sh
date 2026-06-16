#!/usr/bin/env bash
# reality_check.sh — validate Telegram configuration and start first dogfooding session
#
# Purpose: help the operator validate that Telegram delivery works before relying
# on it for operational monitoring.
#
# Run from the project root:
#   bash scripts/reality_check.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# Load .env if it exists
if [[ -f .env ]]; then
  # shellcheck disable=SC2046
  export $(grep -v '^#' .env | grep -v '^$' | xargs)
fi

PASS="[PASS]"
FAIL="[FAIL]"
INFO="[INFO]"
WARN="[WARN]"

echo ""
echo "============================================"
echo "  Quartermaster — Reality Check"
echo "============================================"
echo ""

# -----------------------------------------------------------------------
# Step 1: Validate environment
# -----------------------------------------------------------------------
echo "--- Step 1: Environment Validation ---"
echo ""

errors=0

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "$FAIL TELEGRAM_BOT_TOKEN is not set in .env"
  errors=$((errors + 1))
else
  echo "$PASS TELEGRAM_BOT_TOKEN is set (not shown for security)"
fi

if [[ -z "${TELEGRAM_CHAT_ID:-}" ]]; then
  echo "$FAIL TELEGRAM_CHAT_ID is not set in .env"
  errors=$((errors + 1))
else
  echo "$PASS TELEGRAM_CHAT_ID is set: ${TELEGRAM_CHAT_ID}"
fi

enabled="${TELEGRAM_ENABLED:-false}"
if [[ "$enabled" != "true" ]]; then
  echo "$WARN TELEGRAM_ENABLED is not 'true' — delivery is disabled"
  echo "     Set TELEGRAM_ENABLED=true in .env to activate"
else
  echo "$PASS TELEGRAM_ENABLED=true"
fi

if [[ $errors -gt 0 ]]; then
  echo ""
  echo "$FAIL Configuration incomplete. Fix the above errors and re-run."
  exit 1
fi

echo ""

# -----------------------------------------------------------------------
# Step 2: Telegram connectivity check
# -----------------------------------------------------------------------
echo "--- Step 2: Telegram Connectivity ---"
echo ""

API_URL="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe"
RESPONSE=$(curl -s --max-time 10 "$API_URL" 2>/dev/null || echo '{"ok":false}')
IS_OK=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(str(d.get('ok',False)).lower())" 2>/dev/null || echo "false")

if [[ "$IS_OK" == "true" ]]; then
  BOT_NAME=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('result',{}).get('username','?'))" 2>/dev/null || echo "?")
  echo "$PASS Bot API reachable. Bot username: @${BOT_NAME}"
else
  echo "$FAIL Bot API call failed. Check TELEGRAM_BOT_TOKEN and network connectivity."
  echo "     Response: ${RESPONSE:0:200}"
  exit 1
fi

echo ""

# -----------------------------------------------------------------------
# Step 3: Send test message
# -----------------------------------------------------------------------
echo "--- Step 3: Test Message ---"
echo ""

TEST_MSG="<b>Quartermaster — Reality Check</b>%0A%0AThis is a test message sent by the reality_check.sh script.%0A%0AIf you see this, Telegram delivery is working correctly.%0A%0A<i>$(date -u '+%Y-%m-%d %H:%M UTC')</i>"
SEND_URL="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage"
SEND_RESPONSE=$(curl -s --max-time 10 \
  -X POST "$SEND_URL" \
  -H "Content-Type: application/json" \
  -d "{\"chat_id\": \"${TELEGRAM_CHAT_ID}\", \"text\": \"${TEST_MSG}\", \"parse_mode\": \"HTML\"}" \
  2>/dev/null || echo '{"ok":false}')

SEND_OK=$(echo "$SEND_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(str(d.get('ok',False)).lower())" 2>/dev/null || echo "false")

if [[ "$SEND_OK" == "true" ]]; then
  echo "$PASS Test message sent successfully. Check your Telegram chat."
else
  echo "$FAIL Failed to send test message. Check TELEGRAM_CHAT_ID and bot permissions."
  echo "     Response: ${SEND_RESPONSE:0:300}"
  exit 1
fi

echo ""

# -----------------------------------------------------------------------
# Step 4: Run a scan (if API is reachable)
# -----------------------------------------------------------------------
echo "--- Step 4: Scan + Digest ---"
echo ""

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
API_BASE="http://localhost:${PORT}"

# Check if the service is running
if curl -s --max-time 3 "${API_BASE}/health" > /dev/null 2>&1; then
  echo "$INFO API server is running at ${API_BASE}"

  echo "$INFO Triggering a scan..."
  SCAN_RESPONSE=$(curl -s --max-time 60 -X POST "${API_BASE}/scan" -H "Content-Type: application/json" -d '{"target":"."}' 2>/dev/null || echo '{}')
  SCAN_STATUS=$(echo "$SCAN_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null || echo "unknown")
  echo "$INFO Scan result: ${SCAN_STATUS}"

  echo "$INFO Requesting daily digest..."
  DIGEST_RESPONSE=$(curl -s --max-time 30 -X POST "${API_BASE}/delivery/digest/daily" 2>/dev/null || echo '{"sent":false}')
  DIGEST_SENT=$(echo "$DIGEST_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(str(d.get('sent',False)).lower())" 2>/dev/null || echo "false")
  if [[ "$DIGEST_SENT" == "true" ]]; then
    echo "$PASS Daily digest sent via API."
  else
    echo "$WARN Digest API call returned: ${DIGEST_RESPONSE:0:200}"
    echo "     (The digest endpoint may not be wired to an API route yet.)"
    echo "     Delivery will happen via the scheduled job at 08:00 UTC."
  fi
else
  echo "$WARN API server not reachable at ${API_BASE}"
  echo "     Skipping scan trigger and digest send."
  echo "     Start the service with: make run (or uvicorn backend.main:app)"
fi

echo ""

# -----------------------------------------------------------------------
# Step 5: Operational checklist
# -----------------------------------------------------------------------
echo "--- Operational Checklist ---"
echo ""
echo "  [ ] Telegram test message received in your chat"
echo "  [ ] Bot is admin in the target chat/channel"
echo "  [ ] TELEGRAM_ENABLED=true in .env"
echo "  [ ] Service is running: systemctl status quartermaster (or equivalent)"
echo "  [ ] Daily digest scheduled at 08:00 UTC — will arrive tomorrow morning"
echo "  [ ] Review quiet hours: TELEGRAM_QUIET_HOURS_START=${TELEGRAM_QUIET_HOURS_START:-22:00} to ${TELEGRAM_QUIET_HOURS_END:-08:00} UTC"
echo "  [ ] Delivery health visible at: GET /operations/selfcheck"
echo ""
echo "============================================"
echo "  Reality check complete."
echo "  Start your first dogfooding session."
echo "============================================"
echo ""
