# Scanning Protocol

## Rules

1. Scanners are read-only. No file writes, no process kills, no config changes.
2. Each scanner inherits from `BaseScanner` and implements `_scan(target)`.
3. Scanners log their start, completion, and result summary at INFO level.
4. Results are structured dicts — always JSON-serializable.
5. Scanners must handle errors gracefully and return `{"error": "..."}` rather than raise.
6. Scanner results are stored to SQLite immediately after completion.
7. No scanner result is ever sent to an external API automatically.

## Naming

Scanners follow the naming convention: `{domain}_scanner.py`

Examples: `repo_scanner`, `process_scanner`, `docker_scanner`, `network_scanner`

## Result Schema Convention

```json
{
  "target": "string — what was scanned",
  "scanner": "string — scanner name",
  "status": "completed | error",
  "data": {}
}
```
