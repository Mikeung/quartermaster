# DRIFT_SPEC.md
# Formal Specification: Valid Drift Detection

**Version:** 1.0  
**Status:** Governing  
**Scope:** All drift comparison logic within the Quartermaster scan pipeline

---

## Drift Philosophy

### Definition

**Drift** is a meaningful operational change to a specific target, observable between two consecutive valid snapshots of that same target, where the change has persisted long enough to be distinguished from transient runtime variance.

### What drift is not

| Non-drift | Reason |
|---|---|
| Cross-target comparison result | Different repos, services, or environments are structurally different; their differences are not operational change |
| Ephemeral port appearing or disappearing | OS-assigned sockets are transient by definition |
| LLM provider detected in scan N but not scan N+1 for different target | This is a cross-target artifact, not a change |
| File count varying between a large repo and a small repo | Not a change — a category error |
| Framework detected in language A, not detected in language B | Category error; different target |
| Port number change within the ephemeral range (≥ 32768) | Not a stable listener; not tracked |
| Cosmetic recommendation wording change | Not infrastructure change |
| Snapshot ID sequence gap due to scan failure | Not drift; a coverage gap |

### Governing principle

A drift event must be falsifiable. An operator must be able to:
1. Look at the target directly and confirm the reported change
2. Understand what changed, from what to what, and when
3. Determine whether action is required

A drift event that cannot be confirmed by looking at the target is a false positive.

---

## Snapshot Model

Every scan produces one snapshot per target per scan cycle. Snapshots are the atomic unit of comparison.

### Canonical snapshot schema

```
snapshot_id         INTEGER PRIMARY KEY AUTOINCREMENT
target_id           TEXT NOT NULL           -- stable identifier for the scan target
scope               TEXT NOT NULL           -- 'repo' | 'vps' | 'service' | 'container'
collector_type      TEXT NOT NULL           -- 'filesystem' | 'systemd' | 'network' | 'docker' | 'registry'
environment         TEXT NOT NULL DEFAULT 'production'
captured_at         TIMESTAMP NOT NULL      -- UTC ISO 8601
target_path         TEXT                    -- absolute path for repo/filesystem targets
target_name         TEXT                    -- human-readable label

-- Observed state (scope-dependent fields)
services            JSONB / TEXT            -- systemd unit state
ports               JSONB / TEXT            -- listening ports, stable range only
containers          JSONB / TEXT            -- docker container state
llm_providers       JSONB / TEXT            -- detected LLM SDK presence
frameworks          JSONB / TEXT            -- detected frameworks
primary_language    TEXT
file_count          INTEGER
package_manifest    JSONB / TEXT            -- requirements.txt / package.json contents
kernel_events       JSONB / TEXT            -- OOM kills, kernel errors since last scan

-- Identity and quality
confidence          REAL DEFAULT 1.0        -- snapshot-level confidence (0.0–1.0)
scan_duration_ms    INTEGER
error               TEXT                    -- non-null if scan partially failed
```

### Scope values

| scope | Covers |
|---|---|
| `repo` | Filesystem structure, language, frameworks, LLM packages, file count, CI config |
| `vps` | Systemd services, listening ports (stable range), Docker container state, kernel events |
| `service` | Single systemd unit state, port binding, environment exposure |
| `container` | Single Docker container health, port mapping, image digest |

A single scan cycle produces one snapshot per `(target_id, scope)` pair. A target scanned for both `repo` and `vps` produces two independent snapshots.

---

## Target Identity Rules

### Valid drift comparison

A drift comparison is **valid** if and only if all of the following hold:

```
snapshot_A.target_id      == snapshot_B.target_id
snapshot_A.scope          == snapshot_B.scope
snapshot_A.collector_type == snapshot_B.collector_type
snapshot_A.environment    == snapshot_B.environment
snapshot_A.captured_at     < snapshot_B.captured_at   (A is older)
snapshot_B is the most recent snapshot for this target_id+scope
snapshot_A is the most recent snapshot for this target_id+scope before snapshot_B
```

### Explicitly forbidden comparisons

The following comparisons **must not occur** under any condition:

| Forbidden | Reason |
|---|---|
| `snapshot_A.target_id != snapshot_B.target_id` | Cross-target comparison; produces guaranteed structural noise |
| `snapshot_A.scope != snapshot_B.scope` | Comparing repo state to VPS state is meaningless |
| `snapshot_A.collector_type != snapshot_B.collector_type` | Different data sources; incomparable |
| `snapshot_A.environment != snapshot_B.environment` | Cross-environment comparison is not operational change |
| Comparing by global snapshot_id sequence | Snapshot IDs are not target-scoped; sequential ID comparison crosses targets |

### Implementation requirement

Correct snapshot lookup for drift comparison:

```sql
-- Correct: target-scoped pair lookup
SELECT * FROM snapshots
WHERE target_id = :target_id
  AND scope = :scope
  AND collector_type = :collector_type
  AND environment = :environment
ORDER BY captured_at DESC
LIMIT 2;
-- Returns [current, previous] for the same target
```

```sql
-- FORBIDDEN: global sequential comparison
SELECT * FROM snapshots
WHERE snapshot_id IN (:N, :N+1);
-- This crosses targets when different targets were scanned adjacently
```

---

## Drift Comparison Algorithm

### Step 1: Latest valid snapshot lookup

For each `(target_id, scope, collector_type, environment)` tuple:

1. Query the two most recent snapshots matching all four dimensions
2. If fewer than 2 snapshots exist: no drift comparison possible; log as `insufficient_history`
3. If `captured_at` difference > `max_comparison_window` (default: 36 hours): treat as baseline reset; log as `baseline_gap`; do not generate drift
4. Assign: `previous = older snapshot`, `current = newer snapshot`

### Step 2: Field-level diff

Compare each observable field between `previous` and `current`:

```
For each tracked field F in current:
  if F not in previous:
    record as ADDED(F, current[F])
  elif previous[F] != current[F]:
    record as CHANGED(F, previous[F], current[F])

For each tracked field F in previous:
  if F not in current:
    record as REMOVED(F, previous[F])
```

Field comparison rules:

| Field | Comparison method |
|---|---|
| `services` | Set diff on service names and states |
| `ports` | Set diff on `(port, proto, process)` tuples, stable range only |
| `containers` | Set diff on container names; health state changes |
| `llm_providers` | Set diff on provider names |
| `frameworks` | Set diff on framework names |
| `primary_language` | String equality |
| `file_count` | Absolute delta + percentage change; threshold applies |
| `package_manifest` | Set diff on package names (versions are informational, not drift triggers) |
| `kernel_events` | New events since last snapshot; cumulative |

### Step 3: Confidence handling

If `previous.confidence < 0.5` or `current.confidence < 0.5`:
- Downgrade all resulting drift events by one severity level
- Mark drift event as `low_confidence_source: true`
- Do not suppress — log with confidence annotation

### Step 4: Evidence window

For each candidate drift event:
1. Check if the same drift event fired in the most recent previous cycle
2. If yes: increment `persistence_count` on existing drift finding; do not create a new drift event
3. If no: create new drift event with `persistence_count = 1`

This prevents re-alerting on the same drift every 6 hours when underlying state has not changed.

### Step 5: Debounce logic

A drift event is **suppressed from delivery** (but logged) if:
- `finding_type` is `port_closed` or `port_opened` AND port is in ephemeral range
- `persistence_count == 1` AND `severity == LOW` AND scan cycle interval < 6 hours
- The same `finding_id` was delivered in the prior 6-hour cycle AND severity is LOW

HIGH severity drift events bypass debounce. They are delivered immediately.

---

## Drift Severity Rules

### HIGH

These drift events require operator review within one business day.

| Finding type | Trigger condition |
|---|---|
| `stable_listener_disappeared` | A port in the stable range (< 32768) that was present for ≥ 2 consecutive cycles is no longer listening |
| `service_disappeared` | A systemd service that was active for ≥ 2 consecutive cycles is no longer running |
| `service_failed` | A systemd service transitioned to `failed` state |
| `public_exposure_new` | A port newly bound to `0.0.0.0` (not previously bound that way) |
| `container_unhealthy` | A Docker container health check transitioned from `healthy` to `unhealthy` |
| `kernel_oom_kill` | OOM killer fired; includes process name and RSS |
| `kernel_hardware_error` | Kernel hardware error event detected in journal |
| `credential_exposure_new` | A new service unit with credentials in `ExecStart=` line detected |

### MEDIUM

These drift events should be reviewed within one week.

| Finding type | Trigger condition |
|---|---|
| `llm_provider_changed` | LLM provider set changed on an intra-target comparison |
| `framework_changed` | Framework set changed on an intra-target comparison |
| `primary_language_changed` | Primary language changed on an intra-target comparison |
| `container_removed` | A Docker container no longer present |
| `large_file_count_change` | File count changed by > 50% AND > 500 files on same target |
| `new_ci_system` | CI/CD system detected that was not present in previous scan |

### LOW

Informational. Delivered in daily report. Not Telegram'd unless promoted.

| Finding type | Trigger condition |
|---|---|
| `package_added` | New package in manifest |
| `package_removed` | Package removed from manifest |
| `small_file_count_change` | File count changed by > 20% but < 50% on same target |
| `docker_image_changed` | Container image digest changed |

### NOT DRIFT (suppress entirely)

| Condition | Disposition |
|---|---|
| Cross-target snapshot comparison | Forbidden; implementation error if reached |
| Ephemeral port (≥ 32768) change | Suppressed; logged at DEBUG |
| Service state fluctuating within `active` | Not drift |
| SSH kex errors in journal | Not operational drift; background internet noise |
| File count change < 20% | Below significance threshold |
| Snapshot ID sequence gap (missing scan) | Coverage gap, not drift; log separately |

---

## Ephemeral Noise Suppression

### Ephemeral port range

Linux default ephemeral range: 32768–60999.  
Actual range on this system: read from `/proc/sys/net/ipv4/ip_local_port_range` at scan startup.  
Store as config; refresh on service restart.

All ports within the ephemeral range are **excluded from port drift comparison**.

### Stability window

A port must be observed as listening in **≥ 2 consecutive scan cycles** before it enters the stable port baseline. This prevents a short-lived service from appearing in the stable listener set.

```
stable_ports[target] = {
  port
  for port in current_ports[target]
  if port in previous_ports[target]
  AND port < ephemeral_range_start
}
```

### Persistence thresholds

| Field | Minimum observation cycles before drift fires |
|---|---|
| Port listening | 2 |
| Service state | 1 (service failures are immediate) |
| LLM provider | 2 |
| Framework | 2 |
| Primary language | 2 |
| File count (LOW) | 2 |
| File count (MEDIUM/HIGH) | 1 |

### Temporal smoothing

For LOW severity findings, do not fire on the first observation of a change. Fire on the second consecutive observation. This prevents transient scan-time anomalies (e.g., a package install mid-scan) from generating alerts.

HIGH severity findings (service failure, OOM, public exposure) bypass temporal smoothing.

---

## Confidence Model

Confidence is a property of a snapshot and, derived from it, of a drift event.

### Snapshot-level confidence

| Condition | Confidence |
|---|---|
| Full scan completed, all collectors succeeded | 1.0 |
| One collector failed; others succeeded | 0.75 |
| Multiple collectors failed | 0.5 |
| Scan timed out | 0.25 |
| Scan error (exception) | 0.0 (snapshot stored for audit; not used in drift) |

### Drift-event-level confidence

```
drift_confidence = min(previous_snapshot.confidence, current_snapshot.confidence)
```

If `drift_confidence < 0.5`: drift event is stored but not delivered. Logged as `suppressed_low_confidence`.

### Future fields (not implemented in sprint, reserved)

```
evidence_count      INTEGER    -- number of independent signals corroborating the finding
stability_score     REAL       -- persistence_count / total_cycles_observed
persistence_score   REAL       -- fraction of cycles where finding was present
```

---

## Drift Output Contract

Every drift event emitted by the system **must** include the following fields. An event missing any required field is malformed and must be rejected by the delivery pipeline.

### Required fields

```
drift_id            TEXT       -- deterministic hash; see FINDING_IDENTITY_SPEC.md
target_id           TEXT       -- stable target identifier
target_path         TEXT       -- human-readable path or name
scope               TEXT       -- 'repo' | 'vps' | 'service' | 'container'
finding_type        TEXT       -- from severity rule table above
severity            TEXT       -- 'HIGH' | 'MEDIUM' | 'LOW'
confidence          REAL       -- 0.0–1.0
previous_value      TEXT       -- what was observed before (serialized)
current_value       TEXT       -- what is observed now (serialized)
previous_snapshot_id INTEGER   -- FK to snapshots table
current_snapshot_id  INTEGER   -- FK to snapshots table
first_seen          TIMESTAMP  -- UTC ISO 8601; when this drift finding was first observed
last_seen           TIMESTAMP  -- UTC ISO 8601; most recent observation
persistence_count   INTEGER    -- how many consecutive cycles this drift has been observed
delivered           BOOLEAN    -- whether this event has been sent via Telegram/report
suppressed          BOOLEAN    -- whether this event was suppressed (with reason)
suppression_reason  TEXT       -- null if not suppressed
```

### Optional fields

```
evidence            TEXT       -- raw evidence text (e.g., journalctl line, ss output)
operator_note       TEXT       -- manual annotation (future)
```

---

## Anti-Patterns

The following patterns are **explicitly forbidden** in any implementation of drift detection within this system.

### Sequential global snapshot comparison

```python
# FORBIDDEN
for i in range(len(snapshots) - 1):
    diff(snapshots[i], snapshots[i+1])

# CORRECT
for target in targets:
    pair = get_latest_two_snapshots(target_id=target.id, scope=target.scope)
    if pair:
        diff(pair.previous, pair.current)
```

### Unstable target identity

Generating target identifiers from mutable properties (path that may change, hostname that may change, service display name) will cause drift baseline loss. Target IDs must be defined explicitly in configuration and never auto-generated from runtime state.

### Cosmetic drift alerts

Changes to recommendation wording, report formatting, or presentation metadata are not drift events. Drift is infrastructure change, not documentation change.

### Duplicate drift generation

The same `(target_id, scope, finding_type, previous_value, current_value)` tuple must not produce more than one active drift event. Subsequent observations of the same condition increment `persistence_count` on the existing record; they do not create new records.

### Severity inflation

Do not escalate drift severity because a finding has been persisting without operator acknowledgment. Persistence without acknowledgment is an operator workflow problem, not a reason to escalate severity. Severity reflects the nature of the change, not the operator's response to it.

---

*This document governs all drift comparison logic. Implementations that deviate require a documented exception with rationale.*  
*Advisory only — operational decisions require human review.*
