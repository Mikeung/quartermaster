#!/usr/bin/env bash
# backup.sh — create a point-in-time backup of the operational memory database
#
# Usage:
#   ./scripts/backup.sh [backup_dir]
#
# Default backup dir: ./backups/
#
# Creates: backups/operational_memory_YYYYMMDD_HHMMSS.db
# Uses SQLite's .backup command for a consistent snapshot (WAL-safe).
#
# Does NOT:
#   - Stop the server (SQLite WAL mode supports hot backups)
#   - Compress the backup (use gzip if needed)
#   - Delete old backups (manage retention manually)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKUP_DIR="${1:-${REPO_ROOT}/backups}"

log() { echo "[backup] $*"; }
die() { echo "[backup] ERROR: $*" >&2; exit 1; }

# Locate DB
DB_PATH="${REPO_ROOT}/data/operational_memory.db"
if [[ ! -f "${DB_PATH}" ]]; then
    # Try to read from .env
    if [[ -f "${REPO_ROOT}/.env" ]]; then
        DB_PATH=$(grep -E '^DB_PATH=' "${REPO_ROOT}/.env" | cut -d= -f2 | tr -d '"' || true)
        DB_PATH="${DB_PATH:-${REPO_ROOT}/data/operational_memory.db}"
    fi
fi
if [[ ! -f "${DB_PATH}" ]]; then
    die "Database not found at ${DB_PATH}. Has the server run yet?"
fi

mkdir -p "${BACKUP_DIR}"

TIMESTAMP=$(date -u +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/operational_memory_${TIMESTAMP}.db"

log "Backing up ${DB_PATH} → ${BACKUP_FILE}"
sqlite3 "${DB_PATH}" ".backup '${BACKUP_FILE}'"

SIZE=$(du -sh "${BACKUP_FILE}" | cut -f1)
log "Backup complete: ${BACKUP_FILE} (${SIZE})"
log ""
log "To restore, run: ./scripts/restore.sh ${BACKUP_FILE}"
