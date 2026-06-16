#!/usr/bin/env bash
# env_validate.sh — validate environment and dependency readiness
#
# Checks:
#   - Python version (3.10+)
#   - Virtual environment activated
#   - Required Python packages installed
#   - .env file present and readable
#   - SQLite database directory writable
#   - Port availability (default 8000)
#
# Usage:
#   ./scripts/env_validate.sh

set -euo pipefail

PASS=0
WARN=0
FAIL=0

ok()   { echo "  [OK]   $*"; ((PASS++)); }
warn() { echo "  [WARN] $*"; ((WARN++)); }
fail() { echo "  [FAIL] $*"; ((FAIL++)); }

echo ""
echo "=== Environment Validation ==="
echo ""

# 1. Python version
PY_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
if [[ "$PY_MAJOR" -ge 3 && "$PY_MINOR" -ge 10 ]]; then
  ok "Python $PY_VERSION"
else
  fail "Python $PY_VERSION — requires 3.10+"
fi

# 2. Virtual environment
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  ok "Virtual environment active: $VIRTUAL_ENV"
else
  warn "No virtual environment active — consider activating venv"
fi

# 3. Required packages
check_package() {
  local pkg="$1"
  if python3 -c "import $pkg" 2>/dev/null; then
    ok "Package: $pkg"
  else
    fail "Missing package: $pkg — run: pip install $pkg"
  fi
}

check_package fastapi
check_package uvicorn
check_package pydantic
check_package pydantic_settings
check_package apscheduler
check_package psutil

# Optional HTTP libraries for SDK
if python3 -c "import httpx" 2>/dev/null; then
  ok "Package: httpx (SDK transport)"
elif python3 -c "import requests" 2>/dev/null; then
  ok "Package: requests (SDK transport fallback)"
else
  warn "Neither httpx nor requests installed — SDK transport unavailable. Install: pip install httpx"
fi

# 4. .env file
if [[ -f ".env" ]]; then
  ok ".env file present"
else
  warn ".env file not found — using defaults from config.py"
fi

# 5. Data directory
DB_DIR="data"
if [[ -d "$DB_DIR" ]]; then
  if [[ -w "$DB_DIR" ]]; then
    ok "Data directory writable: $DB_DIR"
  else
    fail "Data directory not writable: $DB_DIR"
  fi
else
  if mkdir -p "$DB_DIR" 2>/dev/null; then
    ok "Data directory created: $DB_DIR"
  else
    fail "Cannot create data directory: $DB_DIR"
  fi
fi

# 6. SQLite availability
if python3 -c "import sqlite3; sqlite3.connect(':memory:').close()" 2>/dev/null; then
  SQLITE_VER=$(python3 -c "import sqlite3; print(sqlite3.sqlite_version)")
  ok "SQLite $SQLITE_VER"
else
  fail "SQLite not available — check Python installation"
fi

# 7. Port availability
PORT="${PORT:-8000}"
if ss -tlnp 2>/dev/null | grep -q ":${PORT} " || netstat -tlnp 2>/dev/null | grep -q ":${PORT} "; then
  warn "Port $PORT is already in use — service may already be running"
else
  ok "Port $PORT available"
fi

echo ""
echo "--- Summary ---"
echo "  Passed:   $PASS"
echo "  Warnings: $WARN"
echo "  Failed:   $FAIL"
echo ""

if [[ $FAIL -gt 0 ]]; then
  echo "Environment has $FAIL issue(s) to fix before running the service."
  exit 1
elif [[ $WARN -gt 0 ]]; then
  echo "Environment ready with $WARN warning(s)."
  exit 0
else
  echo "Environment looks good."
  exit 0
fi
