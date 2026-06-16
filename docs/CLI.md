# CLI Reference

The `cli/main.py` module provides a lightweight command-line interface for
common operational tasks. No TUI framework — plain terminal output designed
to be readable and script-friendly.

**Requirements:** `httpx` or `requests` (for commands that call the service API)

---

## Installation / Setup

```bash
# From the project root
python -m cli.main --help

# Or add an alias
alias aom="python -m cli.main"
```

---

## Global Flag

| Flag | Default | Description |
|---|---|---|
| `--url` | `http://localhost:8000` | Base URL of the operational memory service |

---

## Commands

### `health`

Check service health.

```bash
python -m cli.main health
python -m cli.main health --url http://my-server:8000
```

Example output:
```
=== Health Check ===

  [OK]  Service reachable — status: operational
  [OK]  Version: 0.1.0
```

---

### `projects`

List all registered projects.

```bash
python -m cli.main projects
```

Example output:
```
=== Registered Projects ===

  my-rag-app                      RAG Application              [active]
  email-pipeline                  Email Triage Pipeline         [active]
  old-experiment                  Old Experiment               [archived]
```

---

### `register`

Register a new project namespace.

```bash
python -m cli.main register my-new-app
python -m cli.main register my-new-app --name "My New App" --tags "production,rag"
python -m cli.main register my-new-app --retention-profile extended
```

| Argument | Description |
|---|---|
| `project_id` | Required. Lowercase, dashes-ok, 3–64 chars |
| `--name` | Display name (defaults to project_id) |
| `--description` | Short description |
| `--tags` | Comma-separated tags |
| `--retention-profile` | `minimal`, `standard`, `extended` (default: `standard`) |
| `--deployment-profile` | `minimal`, `standard`, `extended` (default: `standard`) |

---

### `survivability`

Show the long-running survivability summary.

```bash
python -m cli.main survivability
python -m cli.main survivability --report    # markdown report
```

Example output:
```
=== Survivability Summary ===

  Status: [OK] OK
  Outlook: stable

  Checks:
    [OK]  Database Growth Rate — 0.14 MB/day (threshold: 10 MB/day)
    [OK]  Retention Backlog — oldest snapshot: 8 days
    [OK]  Scheduler Health — 1 job(s) running, no stale or degraded
    [OK]  Stale Archived Projects — no archived projects
    [OK]  Ingestion Pressure Trend — stable week-over-week
```

---

### `pressure`

Show per-project ingestion pressure.

```bash
python -m cli.main pressure
```

Example output:
```
=== Ingestion Pressure ===

  Projects checked: 2
  [OK]  OK: 2
```

---

### `storage`

Show storage overview across all projects.

```bash
python -m cli.main storage
```

Example output:
```
=== Storage Overview ===

  Total snapshots:  142
  Total LLM events: 8320

  Project breakdown:
    my-rag-app                      snaps:    98  events:   6100  share: 69.0%
    email-pipeline                  snaps:    44  events:   2220  share: 31.0%
```

---

### `retention`

Preview the retention plan (always dry-run — never deletes).

```bash
python -m cli.main retention
```

Example output:
```
=== Retention Preview (dry-run) ===

  Snapshots to delete: 12
  Snapshots to keep:   130
  LLM events to delete: 800

  [WARN] Run retention with dry_run=false to delete 812 records
```

To actually execute retention, use the API directly:
```bash
curl -X POST http://localhost:8000/operations/retention?dry_run=false
```

---

### `report`

Generate a markdown report and print to stdout.

```bash
python -m cli.main report provider
python -m cli.main report workflow
python -m cli.main report latency
python -m cli.main report tokens
python -m cli.main report errors
```

| Kind | Description |
|---|---|
| `provider` | Usage breakdown by provider |
| `workflow` | Workflow economics and activity |
| `latency` | Latency trend analysis |
| `tokens` | Token concentration and amplification |
| `errors` | Error rate trends |

Redirect to file:
```bash
python -m cli.main report provider > /tmp/provider-report.md
```

---

### `send-test`

Send a minimal synthetic test event to verify the ingestion pipeline.

```bash
python -m cli.main send-test --project my-rag-app
```

Example output:
```
=== Ingestion Smoke Test — project: my-rag-app ===

  [OK]  Event accepted (47ms)
```

---

### `integration-check`

Validate integration setup against a running service. Runs 8 checks:
1. Project ID format validation
2. Service connectivity
3. Service version presence
4. Project registration status
5. Ingestion endpoint reachability
6. Test event acceptance
7. Privacy gate verification
8. Required field rejection

```bash
python -m cli.main integration-check --project my-rag-app
python -m cli.main integration-check --project my-rag-app --json   # JSON output
```

Example output:
```
=== Integration Check — http://localhost:8000  project: my-rag-app ===

  Overall: READY
  Checks passed: 8/8
    [OK]  Project ID Format: 'my-rag-app' is a valid project ID format
    [OK]  Service Connectivity: Service reachable (12ms)
    [OK]  Service Version: Version: 0.1.0
    [OK]  Project Registration: Project 'my-rag-app' is registered and active
    [OK]  Ingestion Endpoint: LLM ingestion endpoint reachable (/llm/storage OK)
    [OK]  Test Event Acceptance: Test event accepted (31ms)
    [OK]  Privacy Gate: Privacy gate correctly rejected forbidden 'prompt' field
    [OK]  Required Field Validation: Service correctly rejected incomplete payload
```

---

## Script-Friendly Usage

Exit codes:
- `0` — success / all checks passed
- `1` — failure / checks failed

Pipe to file:
```bash
python -m cli.main report provider > report.md
python -m cli.main survivability --report > survivability.md
```

JSON output (where supported):
```bash
python -m cli.main integration-check --project my-app --json | jq '.ready'
```

Cron example:
```bash
# Daily survivability check at 08:00
0 8 * * * cd /opt/quartermaster && python -m cli.main survivability >> /var/log/aom-survivability.log 2>&1
```
