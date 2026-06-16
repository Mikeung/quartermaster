# Understanding Layer MVP — Specification

Status: active · Version 1.0 · 2026-05-31
Governs: the six-question understanding contract realized as Project Profiles
(`reports/projects/`). See also [`PROJECT_PROFILE_SPEC.md`](PROJECT_PROFILE_SPEC.md),
[`INDEX_VISION.md`](INDEX_VISION.md), and the charter [`../UNDERSTANDING_ERA.md`](../UNDERSTANDING_ERA.md).

---

## 1. Purpose

The Understanding Layer turns **discovery output** (raw facts about repos, services,
processes, costs) into **understanding**: a plain-language, evidence-backed explanation
of each project on an unfamiliar VPS, such that a new operator can understand it
**without asking the original builders**.

- Discovery is an input. Reports are an output. **Understanding is the objective.**
- The qualifying question for any work: *"Does this improve understanding of an
  unfamiliar VPS?"*

---

## 2. The Six Questions

Every project must be explainable through six questions. This is the contract.

| Question | What it must answer |
|----------|---------------------|
| **WHO** | Who works on it? Who uses it? Who depends on it? |
| **WHAT** | What is this project? |
| **WHY** | Why does it exist? What mission does it serve? |
| **WHERE** | Where does it live? — repositories, services, containers, ports, databases, external dependencies |
| **WHEN** | When is it active? When was it last modified? What is its activity pattern? |
| **WHAT IF** | What happens if it disappears? If it stops running? If a major dependency fails? If significant drift occurs? |

---

## 3. The Answer Contract — Answer + Confidence + Evidence

**Every** section must contain three parts. A section without all three is incomplete.

### 3.1 Answer
Plain language. Written for a competent operator who has never seen this system.
Prefer fewer correct statements over many speculative ones.

### 3.2 Confidence
Exactly one of:

| Level | Meaning |
|-------|---------|
| **High** | Directly stated in evidence (e.g. a README, a config value, a git fact). |
| **Medium** | Inferred from consistent signals; reasonable but not explicit. |
| **Low** | Weakly supported; a lead, not a fact. |

A section may carry mixed-confidence sub-claims (state them), but must give an overall level.

### 3.3 Evidence
The observable facts the answer rests on — file paths, scan fields, git output,
incident records, log lines. Each evidence item should be specific enough that a
reader can independently verify it (e.g. `package.json` `dev: next dev -p 3100`, not
"the config").

---

## 4. Hard Rules

1. **Evidence first.** No answer without evidence.
2. **Confidence is mandatory** on every section.
3. **Unknown is allowed.** "Cannot be determined from observable evidence" is a valid,
   useful answer — record it explicitly with the reason.
4. **Hallucination is forbidden.** No invented purpose, owner, dependency, or history.
   If it isn't in the evidence, it isn't in the answer.
5. **Observable evidence only.** Code, configs, processes, containers, git history,
   logs, costs, incidents, prior reports. **Never ask the builders.**
6. **Inference is labeled.** When an answer is inferred (e.g. a bare process attributed
   to a project), say so and lower the confidence accordingly.
7. **Determinism.** The same evidence must yield the same understanding. No
   probabilistic prose; no LLM-invented facts.

---

## 5. Allowed Evidence Sources

README and markdown docs · repository structure · source code · dependency manifests ·
service / unit / compose files · listening ports (project-specific only — host-wide
ports are shared and must not be attributed to one project) · runtime processes ·
containers · logs · git history (authors, commit cadence, first/last commit) ·
incident reports · daily reports · cost / spend records · workflow inferences ·
project-context registry.

---

## 6. MVP Scope

- **In scope:** per-project Project Profiles answering all six questions with the
  Answer + Confidence + Evidence contract, stored under `reports/projects/`, plus an
  INDEX entry per project.
- **MVP projects:** Quartermaster, Lesia, HDT Web (first three delivered
  2026-05-31).
- **Out of MVP scope (next):** automatic generation for every discovered project;
  automatic VPS-wide INDEX synthesis; keeping profiles current as the VPS drifts.

---

## 7. Success Test

A new CTO receives **only** the INDEX and the Project Profiles — nothing else, and no
access to the engineers. Without speaking to anyone, they should be able to explain:

- what exists
- what each project does
- why each project exists
- who depends on it
- what would happen if it disappeared

If they cannot, the Understanding Layer is not complete.

---

## 8. Relationship to Prior Work

This layer generalizes the finding-level **4W/6W intelligence**
([`FOUR_W_INTELLIGENCE.md`](FOUR_W_INTELLIGENCE.md), WHAT/WHERE/WHEN/WHICH + WHO/COST)
from individual findings/incidents up to the **project** level (WHO/WHAT/WHY/WHERE/WHEN/
WHAT-IF). The project-context registry (`config/project_context.py`) supplies durable
"what is this / who owns it" facts that don't exist in any single finding.
