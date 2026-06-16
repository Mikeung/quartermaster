#!/usr/bin/env bash
# restore.sh — restore the operational memory database from a backup
#
# Usage:
#   ./scripts/restore.sh <backup_file>
#
# IMPORTANT:
#   - The server must be stopped before restoring.
#   - The current database is renamed to .bak before restore.
#   - This is a destructive operation — confirm before proceeding.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

log() { echo "[restore] $*"; }
die() { echo "[restore] ERROR: $*" >&2; exit 1; }

BACKUP_FILE="${1:-}"
if [[ -z "${BACKUP_FILE}" ]]; then
    die "Usage: $0 <backup_file>"
fi
if [[ ! -f "${BACKUP_FILE}" ]]; then
    die "Backup file not found: ${BACKUP_FILE}"
fi

DB_PATH="${REPO_ROOT}/data/operational_memory.db"
if [[ -f "${REPO_ROOT}/.env" ]]; then
    ENV_DB=$(grep -E '^DB_PATH=' "${REPO_ROOT}/.env" | cut -d= -f2 | tr -d '"' || true)
    DB_PATH="${ENV_DB:-${DB_PATH}}"
fi

log "Restore source:      ${BACKUP_FILE}"
log "Restore destination: ${DB_PATH}"
log ""
log "WARNING: This will replace the current database."
log "The server must be stopped before restoring."
read -r -p "Type 'yes' to confirm: " CONFIRM
if [[ "${CONFIRM}" != "yes" ]]; then
    log "Restore cancelled."
    exit 0
fi

# Rename current DB to .bak
if [[ -f "${DB_PATH}" ]]; then
    BAK="${DB_PATH}.bak_$(date -u +%Y%m%d_%H%M%S)"
    mv "${DB_PATH}" "${BAK}"
    log "Existing database moved to: ${BAK}"
fi

# Copy backup to active location
cp "${BACKUP_FILE}" "${DB_PATH}"
log "Restore complete: ${DB_PATH}"
log ""
log "You can now restart the server."
