#!/usr/bin/env bash
# bootstrap.sh — first-time setup for quartermaster on a VPS
#
# Usage:
#   ./scripts/bootstrap.sh [--profile minimal|standard|extended]
#
# What it does:
#   1. Checks Python version (3.11+)
#   2. Creates a virtualenv if not present
#   3. Installs dependencies
#   4. Creates required directories (data/, data/reports/)
#   5. Copies .env.example to .env if .env does not exist
#   6. Runs a quick config validation
#
# Does NOT:
#   - Start the server (use: uvicorn backend.main:app)
#   - Modify system packages
#   - Require root

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${REPO_ROOT}/.venv"
PROFILE="${2:-standard}"

log() { echo "[bootstrap] $*"; }
warn() { echo "[bootstrap] WARNING: $*" >&2; }
die() { echo "[bootstrap] ERROR: $*" >&2; exit 1; }

# --- Python version check ---
PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "${PYTHON_BIN}" &>/dev/null; then
    die "python3 not found. Install Python 3.11+."
fi
PY_VERSION=$("${PYTHON_BIN}" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "${PY_VERSION}" | cut -d. -f1)
PY_MINOR=$(echo "${PY_VERSION}" | cut -d. -f2)
if [[ "${PY_MAJOR}" -lt 3 || ("${PY_MAJOR}" -eq 3 && "${PY_MINOR}" -lt 11) ]]; then
    die "Python 3.11+ required. Found: ${PY_VERSION}"
fi
log "Python ${PY_VERSION} OK"

# --- Virtualenv ---
if [[ ! -d "${VENV_DIR}" ]]; then
    log "Creating virtualenv at ${VENV_DIR}"
    "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
log "Virtualenv activated"

# --- Dependencies ---
log "Installing dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r "${REPO_ROOT}/requirements.txt"
log "Dependencies installed"

# --- Directories ---
mkdir -p "${REPO_ROOT}/data/reports"
log "Data directories created"

# --- .env ---
if [[ ! -f "${REPO_ROOT}/.env" ]]; then
    if [[ -f "${REPO_ROOT}/.env.example" ]]; then
        cp "${REPO_ROOT}/.env.example" "${REPO_ROOT}/.env"
        log ".env created from .env.example — review and customize before starting"
    else
        warn ".env.example not found — create .env manually before starting"
    fi
else
    log ".env already exists — skipping"
fi

# --- Validate config ---
log "Validating configuration..."
cd "${REPO_ROOT}"
"${PYTHON_BIN}" -c "
from backend.config import settings
print(f'  app_name={settings.app_name}')
print(f'  db_path={settings.db_path}')
print(f'  scan_interval={settings.scan_interval_seconds}s')
print(f'  reports_dir={settings.reports_dir}')
"
log "Configuration valid"

log ""
log "Bootstrap complete. Profile: ${PROFILE}"
log ""
log "To start the server:"
log "  source .venv/bin/activate"
log "  uvicorn backend.main:app --host 0.0.0.0 --port 8000"
log ""
log "To run a health check:"
log "  ./scripts/healthcheck.sh"
