#!/usr/bin/env bash
# update.sh — pull latest code and update dependencies
#
# Usage:
#   ./scripts/update.sh
#
# What it does:
#   1. git pull (fast-forward only)
#   2. pip install -r requirements.txt (upgrade)
#   3. Reports what changed
#
# Does NOT restart the server — do that manually after reviewing changes.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${REPO_ROOT}/.venv"

log() { echo "[update] $*"; }
die() { echo "[update] ERROR: $*" >&2; exit 1; }

cd "${REPO_ROOT}"

# Check for uncommitted changes
if ! git diff --quiet || ! git diff --cached --quiet; then
    die "Uncommitted changes detected. Commit or stash before updating."
fi

# Get current HEAD before pull
BEFORE=$(git rev-parse HEAD)

log "Pulling latest changes..."
git pull --ff-only || die "git pull failed. Resolve conflicts manually."

AFTER=$(git rev-parse HEAD)

if [[ "${BEFORE}" == "${AFTER}" ]]; then
    log "Already up to date."
else
    log "Updated from ${BEFORE:0:8} → ${AFTER:0:8}"
    log "Changes:"
    git log --oneline "${BEFORE}..${AFTER}"
fi

# Update dependencies
if [[ -d "${VENV_DIR}" ]]; then
    log "Updating dependencies..."
    # shellcheck disable=SC1091
    source "${VENV_DIR}/bin/activate"
    pip install --quiet --upgrade -r requirements.txt
    log "Dependencies updated"
else
    log "No virtualenv found — run ./scripts/bootstrap.sh first"
fi

log ""
log "Update complete. Restart the server to apply changes:"
log "  uvicorn backend.main:app --host 0.0.0.0 --port 8000"
