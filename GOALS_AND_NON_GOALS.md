# Goals and Non-Goals

## The Goal

**Explain unfamiliar VPS environments** so a new operator can understand them without
asking the original builders. Understanding is the goal — see
[`UNDERSTANDING_ERA.md`](UNDERSTANDING_ERA.md).

Every project should eventually be explainable through the six questions, each answered
with **Answer + Confidence + Evidence**:

- **WHO** — who works on it, uses it, depends on it
- **WHAT** — what the project is
- **WHY** — why it exists / what mission it serves
- **WHERE** — where it lives (repos, services, ports, databases, external deps)
- **WHEN** — when it is active / last modified / its activity pattern
- **WHAT IF** — what happens if it disappears, stops, loses a dependency, or drifts

Unknown is acceptable. Hallucination is not.

## Supporting Goals (inputs and outputs, not the goal)

These exist *because* they serve understanding:

- Understand repositories automatically *(input: discovery)*
- Detect infrastructure and services *(input: discovery)*
- Reconstruct workflows *(input)*
- Track LLM usage and analyze cost inefficiencies *(input/understanding)*
- Preserve operational memory *(understanding)*
- Generate Project Profiles, reports, and actionable recommendations *(output)*
- Minimize manual operational overhead

Discovery is an input. Reports are an output. If a piece of work does not improve
understanding of an unfamiliar VPS, it is probably not the highest priority.

## Non-Goals

- Autonomous infrastructure control
- Automatic code modification
- Self-healing systems
- Fully autonomous agents
- Kubernetes-first architecture
- Enterprise-scale complexity
- Premature distributed systems
- **Discovery or reporting as ends in themselves** (they serve understanding)
