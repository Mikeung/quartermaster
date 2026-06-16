# FINDING_IDENTITY_SPEC.md
# Formal Specification: Deterministic Operational Finding Identity

**Version:** 1.0  
**Status:** Governing  
**Scope:** All findings, recommendations, and drift events within the Quartermaster system

---

## Identity Philosophy

Operational trust depends on stable identity.

A finding is an observation about the state of a target. If the same observation is made in consecutive scan cycles, it is the same finding — not a new one. If the observation persists for 7 days, it has been observed 28 times across 28 scan cycles. It is still the same finding.

Without stable identity:

- Suppression is impossible — there is no persistent unit to suppress
- Novelty becomes fake — "New Risks" that are 7 days old
- Recurrence tracking breaks — occurrence counts cannot accumulate
- Alert fatigue increases — operators receive the same finding repeatedly with no indication of persistence
- Operator response is corrupted — findings that need attention are indistinguishable from findings that appeared 30 seconds ago

The identity layer is the foundation for all suppression, recurrence tracking, confidence accumulation, and delivery deduplication. It must be implemented before any of those features can function correctly.

---

## Canonical Finding Model

A finding is a normalized, persistent record of an observed operational condition.

### Schema

```
finding_id              TEXT PRIMARY KEY   -- deterministic hash; see Deterministic Hashing
target_id               TEXT NOT NULL      -- stable target identifier
finding_type            TEXT NOT NULL      -- semantic category; see Finding Type Registry
resource                TEXT NOT NULL      -- specific resource within target (port, service name, path, package)
scope                   TEXT NOT NULL      -- 'repo' | 'vps' | 'service' | 'container'
severity                TEXT NOT NULL      -- 'HIGH' | 'MEDIUM' | 'LOW'
collector_type          TEXT NOT NULL      -- scanner that produced the finding

-- Lifecycle
first_seen              TIMESTAMP NOT NULL -- UTC ISO 8601; set on first INSERT, never updated
last_seen               TIMESTAMP NOT NULL -- UTC ISO 8601; updated on each observation
occurrence_count        INTEGER NOT NULL DEFAULT 1  -- incremented on each observation
resolved_at             TIMESTAMP          -- set when finding no longer observed; null if active

-- Delivery state
last_delivered_at       TIMESTAMP          -- most recent Telegram/report delivery
delivery_count          INTEGER NOT NULL DEFAULT 0
suppressed              BOOLEAN NOT NULL DEFAULT FALSE
suppression_reason      TEXT               -- null if not suppressed

-- Content (mutable; identity is not derived from these)
title                   TEXT NOT NULL      -- current human-readable title
description             TEXT               -- current description text
recommendation          TEXT               -- current recommended action

-- Evidence and confidence
evidence                TEXT               -- raw evidence supporting the finding
confidence              REAL NOT NULL DEFAULT 1.0
evidence_count          INTEGER NOT NULL DEFAULT 1
```

### Identity fields vs. content fields

**Identity fields** (used to compute `finding_id`):
- `target_id`
- `finding_type`
- `resource`
- `scope`
- `collector_type`

**Mutable state fields** (updated in-place; never used in `finding_id` computation):
- `severity` — escalation (LOW → HIGH) updates the existing record; does not create a new finding
- `title`
- `description`
- `recommendation`
- `evidence`

Changing the wording of a recommendation does not create a new finding. Severity escalation does not create a new finding. These are state updates to an existing finding record.

---

## Canonicalization Rules

Before computing the hash, normalize the identity fields as follows.

### Normalization procedure

```python
def canonicalize_finding(target_id, finding_type, resource, scope, collector_type):
    return {
        "collector_type": collector_type.strip().lower(),
        "finding_type":   finding_type.strip().lower().replace(" ", "_"),
        "resource":       normalize_resource(resource),
        "scope":          scope.strip().lower(),
        "target_id":      target_id.strip().lower(),
    }

def normalize_resource(resource):
    resource = resource.strip()
    resource = resource.replace("\\", "/")
    resource = resource.rstrip("/")
    resource = resource.lower()
    return resource
```

Severity is NOT included in the canonical payload. It is stored and updated as mutable state on the finding record.

### Field normalization rules

| Field | Rule |
|---|---|
| `target_id` | Strip, lowercase |
| `finding_type` | Strip, lowercase, spaces → underscores |
| `resource` | Strip, lowercase, normalize path separators, remove trailing slash |
| `scope` | Strip, lowercase |
| `collector_type` | Strip, lowercase |
| `severity` | **Not hashed.** Stored as mutable state; updated by `upsert()`. |

### What must NOT affect identity

| Excluded | Reason |
|---|---|
| Timestamps | `first_seen`, `last_seen`, `captured_at` are lifecycle metadata, not identity |
| Wording of title, description, recommendation | Presentation layer; mutable without creating new identity |
| Evidence text | Evidence supports the finding; it does not define it |
| Occurrence count | Lifecycle metadata |
| Confidence score | Quality metadata; separate from identity |
| Scan run ID | Execution context; not identity |
| Report version or format | Presentation metadata |

### Stability requirement

Given the same infrastructure state, the system must produce the same `finding_id` on every scan cycle, regardless of:
- When the scan ran
- What version of the recommendation wording was used
- How many times the finding has been seen before
- Whether the finding was previously suppressed

---

## Deterministic Hashing

### Algorithm

```python
import hashlib
import json

def compute_finding_id(target_id, finding_type, resource, scope, collector_type):
    canonical = canonicalize_finding(
        target_id, finding_type, resource, scope, collector_type
    )
    # Serialize with sorted keys for deterministic output
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    # SHA-256, take first 16 bytes (32 hex chars) for compactness
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"fnd_{digest[:32]}"
```

### Properties

- **Deterministic:** Same inputs always produce same `finding_id`
- **Stable:** `finding_id` does not change when content fields are updated
- **Collision-resistant:** SHA-256 with 128-bit truncation; collision probability negligible at operational scale
- **Prefixed:** `fnd_` prefix distinguishes finding IDs from snapshot IDs and drift IDs in logs and database queries
- **Human-readable length:** 36 characters total (`fnd_` + 32 hex)

### Example

```
Input:
  target_id:      "/srv/telegram-humint"
  finding_type:   "credential_in_unit_file"
  resource:       "tgbot.service"
  scope:          "host"
  collector_type: "security_scanner"
  severity:       "HIGH"     ← stored as state; NOT included in hash

Canonicalized (for hashing):
  {"collector_type":"security_scanner","finding_type":"credential_in_unit_file",
   "resource":"tgbot.service","scope":"host",
   "target_id":"vps"}

finding_id: "fnd_a3f8b2c1d4e5f6a7b8c9d0e1f2a3b4c5"
```

This `finding_id` remains stable regardless of:
- When it was computed
- What recommendation text was generated
- Whether severity changed (MEDIUM → HIGH; same finding_id, severity column updated)
- How many times it has appeared in daily reports
- Whether the description was updated between cycles

---

## Recommendation Identity

Recommendations are a subtype of finding. The same identity model applies.

### Separation of concerns

```
Identity layer:   finding_id (deterministic hash of canonical fields)
Presentation layer: title, description, recommendation text

The presentation layer is MUTABLE.
The identity layer is IMMUTABLE.
```

### Implication

If the recommendation engine improves its wording — e.g., from:
```
"Move credentials from tgbot.service to a mode-600 EnvironmentFile= and rotate the exposed keys."
```
to:
```
"Credentials are visible in the tgbot.service unit file. Move to EnvironmentFile= (chmod 600) and rotate all exposed keys."
```

The `finding_id` does not change. The existing finding record is updated with the new `recommendation` text. `occurrence_count` and `first_seen` are preserved. This is not a new finding.

### Content update on upsert

```python
# On each scan cycle:
canonical_id = compute_finding_id(...)

existing = db.query("SELECT * FROM findings WHERE finding_id = ?", canonical_id)

if existing:
    db.execute("""
        UPDATE findings SET
          last_seen = ?,
          occurrence_count = occurrence_count + 1,
          title = ?,
          description = ?,
          recommendation = ?,
          evidence = ?,
          severity = ?,       -- severity may change; identity does not
          confidence = ?
        WHERE finding_id = ?
    """, [now, title, description, recommendation, evidence, severity, confidence, canonical_id])
else:
    db.execute("""
        INSERT INTO findings (finding_id, target_id, finding_type, resource, scope, severity,
          collector_type, first_seen, last_seen, occurrence_count, title, description,
          recommendation, evidence, confidence)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
    """, [canonical_id, target_id, finding_type, resource, scope, severity,
          collector_type, now, now, title, description, recommendation, evidence, confidence])
```

---

## Recurrence Tracking

### Fields

| Field | Semantics |
|---|---|
| `first_seen` | Timestamp of first observation. Set on INSERT; never updated. |
| `last_seen` | Timestamp of most recent observation. Updated on every upsert. |
| `occurrence_count` | Total number of scan cycles in which this finding was observed. |
| `resolved_at` | Set when a finding is no longer observed. Null if active. |
| `persistence_duration` | Computed field: `last_seen - first_seen` (not stored; derived on query) |

### Resolved findings

A finding is marked resolved when a complete scan of the target does not produce the same `finding_id`:

```python
# After each scan cycle, for each previously active finding on this target:
if finding_id not in current_cycle_finding_ids:
    db.execute("""
        UPDATE findings SET resolved_at = ?
        WHERE finding_id = ? AND resolved_at IS NULL
    """, [now, finding_id])
```

A resolved finding that reappears in a later scan cycle is **re-activated**:

```python
# Same upsert logic; if finding_id exists with resolved_at set:
db.execute("""
    UPDATE findings SET
      resolved_at = NULL,
      last_seen = ?,
      occurrence_count = occurrence_count + 1,
      evidence = ?
    WHERE finding_id = ?
""", [now, evidence, finding_id])
```

Reactivation does not reset `first_seen` or `occurrence_count`. The finding's full history is preserved.

---

## Suppression Rules

### Duplicate suppression

A finding that has already been delivered in the current reporting cycle (same `date(last_delivered_at) == date(now)`) must not be re-delivered in the same cycle.

```python
should_deliver = (
    finding.last_delivered_at is None
    or finding.last_delivered_at.date() < today
)
```

### Recurrence suppression

A persisting finding that has not changed severity must not be delivered as "new" after its first delivery.

Daily report labeling rules:

| Condition | Label in report |
|---|---|
| `occurrence_count == 1` | New |
| `occurrence_count == 2` | Persisting (1 day) |
| `occurrence_count > 2` AND `severity == HIGH` | Persisting (N days) — still requires attention |
| `occurrence_count > 2` AND `severity == MEDIUM` | Persisting (N days) |
| `occurrence_count > 2` AND `severity == LOW` | Suppressed from daily report after 7 days; still stored |

Suppressed LOW findings:
- Remain in the database
- Are visible via query
- Are reported as a count: "14 LOW findings suppressed (recurring > 7 days)"
- Are re-surfaced if severity escalates to MEDIUM or HIGH

### Stale finding expiration

A finding that has `resolved_at` set for > 30 days is archived (moved to `findings_archive` table). It does not appear in active reports. It retains its full history for audit.

### Re-alert thresholds

A previously suppressed finding is re-delivered when:

| Condition | Action |
|---|---|
| Severity escalates | Re-deliver immediately at new severity |
| Finding was resolved and reappeared | Re-deliver as "Reactivated" |
| `occurrence_count` crosses 7, 30, 90 (milestones) | Re-deliver as "Persisting milestone" |
| Operator explicitly clears suppression | Re-deliver on next cycle |

---

## Severity Escalation

Severity is mutable operational state. It does NOT affect finding identity.

A finding that escalates from MEDIUM to HIGH is the same finding — the `finding_id` is
unchanged, `occurrence_count` continues to accumulate, and `first_seen` is preserved.
The `severity` column in the findings table is updated in-place by `upsert()`.

### Escalation procedure

```python
# Severity escalated for an existing finding — same finding_id throughout:
fid = compute_finding_id(target_id, finding_type, resource, scope, collector_type)

# upsert() detects the severity change and logs it, but preserves identity:
finding_store.upsert(
    finding_id=fid,
    severity="HIGH",   # was "MEDIUM" — updates the column, does not change fid
    ...
)
# Result: same finding_id, severity=HIGH, occurrence_count incremented, first_seen unchanged
```

### Audit trail

Severity transitions are logged at INFO level by `upsert()`:
```
Finding severity escalation: fnd_abc123... MEDIUM→HIGH (identity preserved)
```

The `first_seen` timestamp shows when the finding was first detected at any severity.
If the exact transition timestamp is needed, it appears in the application log at the
cycle where `upsert()` logged the escalation.

---

## Delivery Rules

### Per-cycle delivery logic

```
1. Collect all active findings for each target (occurrence_count updated, resolved_at NULL)
2. For each finding:
   a. Compute should_deliver based on last_delivered_at and suppression rules
   b. If should_deliver: include in report/Telegram; update last_delivered_at, delivery_count
   c. If suppressed: include in suppressed count only
3. Daily report structure:
   - New findings (occurrence_count == 1)
   - Persisting HIGH findings (occurrence_count > 1, severity HIGH)
   - Persisting MEDIUM findings (occurrence_count > 1, severity MEDIUM)
   - Suppressed count (LOW findings suppressed > 7 days)
   - Resolved findings in last 24h
```

### Telegram delivery rules

Telegram receives:
- All new HIGH findings immediately (not batched)
- New MEDIUM findings in daily summary
- Persisting HIGH findings in daily summary
- Suppressed counts, not individual suppressed findings
- NOT: recurring MEDIUM or LOW findings after day 2

Telegram does NOT receive:
- Findings labeled "New" that are actually recurring
- Duplicate findings from the same scan cycle
- Individual suppressed findings

### Fake novelty prevention

The word "New" in a report is a contractual claim. It means the finding was not present in the previous scan cycle. Any system that labels a finding "New" when `occurrence_count > 1` is producing a false report.

Implementation check:

```python
label = "New" if finding.occurrence_count == 1 else f"Persisting ({days_since_first_seen(finding)} days)"
```

This check must run at report generation time, not at finding creation time.

---

## Confidence Extension

These fields are reserved in the schema but not fully implemented in the stabilization sprint. They are defined here for forward compatibility.

### Evidence accumulation

```
evidence_count: INTEGER
```

Counts the number of independent signals corroborating the finding. Example: a credential exposure finding has `evidence_count = 2` if detected by both the systemd scanner and the repository scanner.

Confidence derived from evidence count:

| evidence_count | Base confidence |
|---|---|
| 1 | 0.5 |
| 2 | 0.75 |
| ≥ 3 | 0.9 |

### Persistence weighting

```
stability_score: REAL = occurrence_count / total_scan_cycles_for_target
```

A finding present in every scan cycle for 7 days has higher `stability_score` than a finding seen once. A high `stability_score` raises confidence; findings are more likely real if they persist across multiple independent scan runs.

### Confidence gates

| confidence | Delivery behavior |
|---|---|
| ≥ 0.75 | Normal delivery |
| 0.5–0.75 | Delivered with confidence annotation |
| < 0.5 | Suppressed; logged to low_confidence_findings |

---

## Anti-Patterns

The following patterns are **explicitly forbidden** in any implementation of finding management within this system.

### Wording-based IDs

```python
# FORBIDDEN
finding_id = hashlib.md5(recommendation_text.encode()).hexdigest()

# CORRECT
finding_id = compute_finding_id(target_id, finding_type, resource, scope, collector_type)
# severity is passed to upsert() as mutable state, never to compute_finding_id()
```

Recommendation text is mutable. IDs derived from it will break every time wording is improved.

### Timestamp-based identities

```python
# FORBIDDEN
finding_id = f"{target_id}_{datetime.utcnow().isoformat()}"
```

Timestamps guarantee uniqueness by making every finding a new finding. This is the inverse of the requirement.

### Regenerated findings per cycle

```python
# FORBIDDEN
db.execute("DELETE FROM findings WHERE target_id = ?", [target_id])
for f in current_findings:
    db.execute("INSERT INTO findings ...", [...])
```

Delete-and-reinsert destroys `first_seen`, `occurrence_count`, and all history. Use upsert.

### Duplicate recommendation creation

If a scan cycle produces a finding that already exists in the `findings` table (same `finding_id`), the correct action is `UPDATE`. Creating a second row with the same identity fields but a different primary key is a schema violation. The `finding_id` column must have a UNIQUE constraint.

### Identity fields in content-only updates

```python
# FORBIDDEN — using title change to route to a new finding
new_title = "URGENT: " + old_title
finding_id = hash(new_title)   # wrong; title is content, not identity
```

Urgency escalation is expressed by severity change (which updates the severity column on the
existing finding in-place) or by delivery prioritization logic — never by title mutation
creating a new identity.

### Implicit global sequence

```python
# FORBIDDEN
findings = db.query("SELECT * FROM findings ORDER BY id DESC LIMIT 10")
# Assumes recency by row insertion order rather than lifecycle timestamps
```

Always use explicit lifecycle timestamps (`first_seen`, `last_seen`, `resolved_at`) for ordering and filtering.

---

## Finding Type Registry

A controlled vocabulary for `finding_type`. All findings must use a registered type. New types require a spec update.

### Security

| finding_type | Description |
|---|---|
| `credential_in_unit_file` | Credentials visible in systemd unit file (Environment= or ExecStart=) |
| `world_readable_env_file` | .env file with permissions > 600 |
| `port_exposed_publicly` | Service bound to 0.0.0.0 without nginx proxy |
| `credential_exposure_new` | Newly detected credential exposure |

### Infrastructure

| finding_type | Description |
|---|---|
| `stable_listener_disappeared` | Stable port (< 32768) no longer listening |
| `service_disappeared` | Systemd service no longer running |
| `service_failed` | Systemd service in failed state |
| `container_unhealthy` | Docker container health check failed |
| `container_removed` | Docker container no longer present |
| `public_exposure_new` | Port newly bound to 0.0.0.0 |
| `coverage_gap` | Running service with no scan target defined |

### Runtime

| finding_type | Description |
|---|---|
| `kernel_oom_kill` | OOM killer terminated a process |
| `kernel_hardware_error` | Hardware error in kernel journal |
| `kernel_filesystem_error` | Filesystem error in kernel journal |

### Operational

| finding_type | Description |
|---|---|
| `llm_cost_untracked` | LLM provider in use with no token/cost tracking |
| `llm_idempotency_risk` | Scheduled LLM job without idempotency guarantee |
| `llm_rate_limit_risk` | LLM workflow without rate limiting |
| `monitor_blind` | Selfmonitor not running within expected window |
| `delivery_failure` | Git or Telegram delivery failed |

---

*This document governs all finding identity, lifecycle, and delivery logic. Implementations that deviate require a documented exception with rationale.*  
*Advisory only — operational decisions require human review.*
