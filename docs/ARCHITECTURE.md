# Architecture

Quartermaster is organized as a layered pipeline. Each layer has a single responsibility and a clear boundary.

```
┌──────────────────────────────────────────────────────┐
│                 FastAPI HTTP Layer                    │
│   /scan  /topology  /reports  /snapshots  /health    │
└───────────────────────┬──────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────┐
│              Operational Memory (SQLite)              │
│         Append-only. Every scan persisted.           │
└───────────────────────┬──────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────┐
│              Recommendation Engine                    │
│    Advisory output. Evidence-cited. No action.       │
└───────────────────────┬──────────────────────────────┘
                        │
        ┌───────────────┼────────────────┐
        │               │                │
┌───────▼──────┐ ┌──────▼──────┐ ┌──────▼────────────┐
│  Topology    │ │  Workflow    │ │  LLM Cost         │
│  Builder     │ │  Inference  │ │  Intelligence      │
│  (graph)     │ │  (patterns) │ │  (heuristics)      │
└───────┬──────┘ └──────┬──────┘ └──────┬────────────┘
        └───────────────┼────────────────┘
                        │
┌───────────────────────▼──────────────────────────────┐
│         Cognition / Observation Layer                 │
│    Normalized facts from raw scanner output          │
└───────────────────────┬──────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────┐
│                    Scanners                           │
│    repo_scanner  service_scanner  process_scanner    │
│    Read-only. Never modify targets.                  │
└───────────────────────┬──────────────────────────────┘
                        │
              Target Infrastructure
            (repos, processes, ports)
```

---

## Layer Responsibilities

### Scanners (`scanners/`)

Read-only observers. Each scanner reads a specific target type and returns a structured dict. No scanner writes to any external system.

- `repo_scanner` — reads package manifests, framework indicators, env files, CI configs, git state
- `service_scanner` — reads active network listeners via `ss`/`netstat`, docker-compose port declarations
- `process_scanner` — reads running processes from `/proc`

All scanners extend `BaseScanner` and implement `_scan(target)`. The `ScannerRegistry` manages execution and timing.

### Cognition / Observation Layer (`cognition/`)

Normalizes raw scanner output into typed `Observation` objects. Observations are facts: they record what was directly detected, with no interpretation attached.

```python
Observation(
    kind=ObservationKind.DETECTED_LLM_SDK,
    scanner="repo_scanner",
    target="/path/to/repo",
    value="anthropic",
    metadata={"source": "package_manifest"},
)
```

The observation layer is the boundary between **facts** and **inference**. Nothing above this layer is a raw scanner value. Nothing below this layer performs interpretation.

### Topology Builder (`topology/builder.py`)

Consumes scan payload and constructs an in-memory `TopologyGraph` of nodes and edges. Every edge carries:
- a `RelationshipType` (USES_LLM_PROVIDER, RUNS_IN_DOCKER, etc.)
- a `confidence` score
- an `evidence` list explaining why the edge was inferred

The graph is deterministic: same input always produces same output.

### Workflow Inference (`topology/workflow_inference.py`)

Identifies high-level AI workflow patterns from the topology and package evidence. Pattern detection is rule-based (frozenset membership checks, presence conditions). No ML.

Each `InferredWorkflow` carries:
- a workflow type (RAG_PIPELINE, MULTI_AGENT_SYSTEM, etc.)
- a confidence score (0.0–1.0)
- an evidence list (what triggered the detection)
- estimated cost tier

### LLM Cost Intelligence (`llm_intelligence/cost_intelligence.py`)

Generates heuristic cost observations from the topology and inferred workflows. Observations are structural — based on detected patterns, not measured billing data.

Each `CostObservation` carries:
- a severity (info / warning / high)
- an estimated cost tier
- an evidence list

### Recommendation Engine (`reports/recommendation_engine.py`)

Synthesizes topology, workflows, and cost observations into advisory `Recommendation` objects. Every recommendation:
- references the evidence that produced it
- carries a confidence score
- suggests specific investigation (never prescribes action)
- is sorted by confidence descending, impact as tiebreaker

### Operational Memory (`memory/`)

Append-only SQLite store. Every full scan is persisted as an `OperationalSnapshot`. Snapshots are never overwritten or deleted. Drift detection compares the latest snapshot against the previous one.

The append-only constraint is intentional: operational history must be recoverable for audit and trend analysis.

### Domain Models (`topology/domain_models.py`)

Explicit semantic vocabulary for the domain. These models define what the system works with:

- `Asset` — a discovered infrastructure element
- `AssetRelationship` — a detected relationship between assets
- `WorkflowPattern` — a recognized AI workflow pattern
- `DriftEvent` — a detected change between snapshots
- `LLMUsageProfile` — aggregated view of LLM usage
- `RecommendationEvidence` — structured evidence chain

These complement the runtime graph models (`topology/models.py`) without replacing them.

---

## Key Design Decisions

### Facts vs Inference

The system separates what was **observed** (scanner facts) from what was **inferred** (topology edges, workflow patterns, recommendations). Every inference cites its evidence. This is a hard product requirement, not a style preference.

### Deterministic Heuristics

All inference is deterministic: frozenset membership checks, presence conditions, threshold comparisons. No probabilistic ML. This means:
- results are reproducible
- reasoning is auditable
- debugging requires no model introspection

### Append-Only Memory

Snapshots are never mutated. This enables:
- drift detection across arbitrary time windows
- full operational history without backups
- safe concurrent reads without locks

### No Autonomous Action

The system has no write path to any external system. There are no actuators, no mutation APIs, no deployment hooks. Advisory output only.

### SQLite First

SQLite is sufficient for single-repo, single-VPS operational use. The schema is minimal. Migration to Postgres is straightforward if multi-tenant or high-concurrency use emerges — see `docs/decisions/adr-001-sqlite-first.md`.

---

## Evidence Chain Example

A recommendation is never issued without an explicit evidence chain:

```
Observation: anthropic detected in requirements.txt          [repo_scanner]
Observation: docker-compose exposes port 8000                [service_scanner]
  → Inference: Repository uses Anthropic SDK (confidence 0.92)
  → Inference: API_LLM_WRAPPER workflow pattern (confidence 0.80)
    → Cost observation: no usage tracking database detected
      → Recommendation: "Add request-level latency and token tracking"
                         confidence: 0.70 | impact: medium
```

Every level is traceable back to a raw scanner observation.
