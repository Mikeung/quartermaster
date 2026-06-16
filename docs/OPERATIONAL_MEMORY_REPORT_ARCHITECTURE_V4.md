# Operational Memory Report Architecture — V4

Status: Governance approved → Implementation
Owner: Implementation engineer (Claude Code)
Date: 2026-05-30
Supersedes (extends, does not replace): `docs/INCIDENT_REPORTING_SPEC.md`
Governance baseline commit: `df08efc`

---

## 0. Mission

The goal is **not** to generate reports. The goal is to **preserve operational
memory**.

A report must remain understandable by an operator who has forgotten:

- the project,
- the architecture,
- the workflows,
- previous incidents,

and who returns after six months. The report must **reconstruct the necessary
context** from nothing. If a returning operator has to ask a follow-up question
to understand the report, the report has failed.

## 1. Core principle

Reports are the primary product. Everything else (scanning, findings,
notifications) exists to support reports.

Priority order:

1. **Incident reports** — permanent operational-memory artifacts.
2. **Daily reports** — daily operational memory; index into incidents.
3. **Notifications** — ephemeral alerts that point at reports.
4. **Findings** — raw detections that back reports.
5. **Recommendations** — advisory only; *not* the current goal.

Understanding is the current goal, not recommendation.

## 2. Storage model (unchanged from V3, plus two indexes)

```
reports/incidents/YYYY-MM-DD/<incident_id>.md   incident reports (system of record)
reports/incidents/index.md                       full incident index            [NEW in V4]
reports/incidents/open_incidents.md              currently-open incidents        [NEW in V4]
reports/history/YYYY-MM-DD/daily_report.md       daily reports
```

Incident reports MUST be committed and pushed. Daily reports MUST reference
incidents. Incident reports are append-only permanent artifacts.

## 3. Required questions

Every report answers **WHO / WHAT / WHERE / WHEN / WHICH / WHY** — and, above all,
**SO WHAT** (why should the operator care?). V3 already carried the six
accountability dimensions (WHO/WHAT/WHERE/WHEN/WHICH/COST). V4 adds the two that
make a report *self-reconstructing*: an explicit **WHY** (root cause) and an
explicit **SO WHAT** (impact), plus the **PROJECT CONTEXT** that lets a stranger
understand the subject at all.

## 4. Incident report format (V4 — fixed section order)

```
<!-- quartermaster-incident metadata: machine-readable header for the index builders -->
# Executive Summary
# PROJECT CONTEXT            [NEW — mandatory]
# WHAT
# WHERE
# WHEN
# WHICH
# WHO
# COST
# WHY DID THIS HAPPEN?       [NEW — mandatory]
# SO WHAT?                   [NEW — mandatory]
# WHICH LLMS WERE INVOLVED?  [NEW]
# INCIDENT CORRELATION       [NEW]
# Evidence
# Timeline
# Recommendations
# Open Questions
# Validation
```

All content is **deterministic** — rendered from the finding's persisted 4W blob,
its evidence, the project-context registry, and per-finding-type maps. No LLM, no
probabilistic content. Same finding + same day → same report (modulo the
generated-at line).

### 4.1 PROJECT CONTEXT (mandatory)

Without this section the report is invalid. It answers, for a stranger:

- **Project** — name of the owning project.
- **Project purpose** — what the project is for.
- **Subsystem** — the subsystem the incident touches.
- **Subsystem purpose** — what the subsystem does.
- **Service** — the concrete service/process.
- **Service purpose** — why it exists.

Context is resolved deterministically from `config/project_context.py`
(`PROJECT_CONTEXT_REGISTRY` + `SERVICE_OWNERSHIP`) keyed on the finding's WHERE
(repository / subsystem / service) and process/resource name. When ownership is
**inferred** (e.g. process name → the VPS's only service of that runtime) the
section states the **attribution basis and confidence** — a guess is never
laundered as fact. When context is genuinely unregistered, the section says so
explicitly and flags it as a context gap (itself an operational signal), rather
than silently omitting it.

### 4.2 WHY DID THIS HAPPEN? (mandatory)

Not *what* happened — *why*. Required fields (deterministic per finding type):

- Immediate cause
- Contributing factors
- Missing safeguards
- Unknown factors
- Confidence level

### 4.3 SO WHAT? (mandatory)

Why the operator should care. Facets:

- Operational impact
- Financial impact
- Project impact
- User impact
- Operator action required

### 4.4 WHICH LLMS WERE INVOLVED?

Models, providers, agents, and cost for the incident (from the 4W WHICH/COST
dimensions), plus links to the relevant cost audits / spend reports
(`reports/costs/*`, the day's daily report economic section, and the spend
ledger). For incidents with no model activity, the section says so explicitly.

### 4.5 INCIDENT CORRELATION

Answers: is this related to previous incidents, spend spikes, deployments, agent
activity, or subsystem rebuilds? Related incident reports are discovered
deterministically by scanning `reports/incidents/` for prior reports that share
the project or the finding type, and are linked by repo-relative path.

## 5. Indexes (NEW)

- `reports/incidents/index.md` — every filed incident, newest first, as a table
  (date · severity · project · type · title · link · status).
- `reports/incidents/open_incidents.md` — the subset whose status is `open`.

Both are rebuilt deterministically by `reports/incident_index.py` from the
machine-readable metadata header embedded at the top of each report. Status is
`open` at write time; `mark_resolved(active_ids)` can flip incidents whose
finding is no longer active to `resolved` (optional, caller-supplied). The index
files are committed/pushed with the reports (they live under
`reports/incidents/`, already staged by `commit_and_push_incidents`).

## 6. Daily report refactor

Daily reports become **daily operational memory**, not a finding/drift dump. The
daily report's Incident Reports section (§7) now:

- summarises the day at the WHO/WHAT/WHERE/WHEN/WHICH/WHY/**SO WHAT** level
  (one-line day-level SO WHAT derived from the day's highest-severity incidents);
- lists **Incident Reports Created Today** with paths;
- lists recent incident reports (cross-reference);
- links the incident **index** and **open incidents** files so an operator can
  navigate directly to all relevant incident reports.

Inline finding→report links (added in V3, task #198) are preserved.

## 7. Validation

Use the three real incidents already on record:

1. **OOM kill** — `kernel_oom_kill` on the `node` process (anon-rss 3.7 GB).
   The `node` process is attributed to **hdt-web** (the VPS's only Next.js /
   Node.js service), with stated confidence and basis.
2. **Gemini spend event** — `runaway_agent_cost`, the real Lesia P7 ledger
   ($100.21, procurement_intel.drain_queue).
3. **Lesia rebuild** — `subsystem_rebuild`, lesia backend/services.

For the OOM report specifically, a reader must be able to answer, **without
asking additional questions**:

- What is the killed service? → PROJECT CONTEXT (service purpose)
- Which project owns it? → PROJECT CONTEXT (project) + WHO
- Why does it exist? → PROJECT CONTEXT (subsystem/service purpose)
- Why was it killed? → WHY DID THIS HAPPEN?
- Why should I care? → SO WHAT?

If any cannot be answered, the architecture fails validation.

> Note on the prompt's `seo-agent-worker` example: that name is a template
> placeholder for "the OOM'd worker." The real recorded OOM subject is the
> `node` process; `seo-agent` is nonetheless a real project on this VPS and is
> registered. The five validation questions are proven against the real `node`
> OOM report (owner: hdt-web).

## 8. Determinism & safety invariants

- Advisory-only: producing a report never mutates infrastructure, spend, repos,
  or provider accounts (CLAUDE.md Read-Only Intelligence Rule).
- Deterministic: every section is a pure function of the persisted finding +
  registry + per-type maps. No LLM, no randomness.
- Unknowns are explicit (`UNKNOWN` sentinel / "context not registered"), never
  silently omitted.
- The project-context registry is operator-editable config — the single source
  of truth for "what is this thing and who owns it."

## 9. Rollback plan

- Additive change set: a new config module (`config/project_context.py`), a new
  index module (`reports/incident_index.py`), additional sections appended to
  `reports/incident_report.py`, an enhanced daily-report §7, and new tests.
- To roll back: revert the implementation commit. Already-filed incident reports
  remain valid append-only history (extra sections/metadata are ignored by older
  code). No schema or data migration occurred.
- To neutralise the new sections without reverting: the section renderers are
  driven by per-type maps with safe defaults; an empty registry degrades to
  explicit "context not registered" rather than failing.
</content>
