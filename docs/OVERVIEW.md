# Overview — how Quartermaster thinks

Quartermaster exists to make an **agent fleet legible**: to let whoever is
responsible for a box full of agents and automations understand it without asking
the people who built it. Monitoring tells you a process is using 80% CPU.
Quartermaster tells you *what that process is, which agent owns it, what it costs,
and what breaks if you stop it.*

## Understanding is the goal

Discovery is an **input**. Reports are an **output**. Understanding is the goal.
Before any feature earns its place it has to answer: *does this help someone
understand an unfamiliar agent fleet?*

## The six questions

Every agent/worker is explained through six questions, and **every answer carries an
answer + a confidence level + the evidence**:

| Question | What it means |
|---|---|
| WHO | who/what depends on it, who owns its spend |
| WHAT | what it is and does |
| WHY | why it exists / what mission it serves |
| WHERE | repos, services, ports, databases, dependencies |
| WHEN | when it's active, when it last changed |
| WHAT IF | what happens if it stops, loses a dependency, or drifts |

Unknown is acceptable. Hallucination is not.

## The overseer is not an AI

Quartermaster watches non-deterministic agents and is itself deterministic — rules,
graphs, and arithmetic over evidence, no LLM in the oversight loop. The watchman
can't hallucinate a finding, be prompt-injected through the logs it reads, or run up
a bill. *Use the stupidity to strain the smarts.* See
[WHY_DETERMINISTIC.md](WHY_DETERMINISTIC.md).

## Advisory-only, read-only

Quartermaster **observes and explains; it never acts.** No deploys, restarts, scaling,
or auto-remediation. This is deliberate: it's safe to run against production because
the worst it can do is read. Humans make every decision. New capabilities must fail
safe and stay opt-in.

## Evidence over inference

Facts first; inference second, and labeled as inference with a confidence. The system
is **deterministic** — the same inputs always produce the same findings — so its
output is auditable, not a black box. Where it can't determine something, it says
"Unknown" with a reason rather than guessing.

## How a finding flows

```
scan (read-only) → topology graph → finding
   → consequence ("what's affected if this is true/down")
   → recommendation ("what to check next")
   → incident report / daily digest / optional alert
```

A finding only **pages** you if it carries a real owner-facing consequence or is
intrinsically critical (security, resource exhaustion, money, a declared dependency
down). Everything else stays in the daily digest. Silence over impact-free noise.

## Cost intelligence (the part agent-fleet managers feel first)

- **Whole view:** total spend per provider, each number tagged with its source —
  the provider's own account usage (authoritative) over an agent's self-reported
  ledger — and a confidence.
- **Attribution by evidence:** a provider key that maps 1:1 to an agent, or an
  agent's own parseable usage. Everything else is honestly **Unattributed**.
- **Investigation:** every unattributed bucket gets a deterministic investigation —
  which key spent it, when it clustered, which on-box process was talking to that
  provider then — narrowed to **candidates with confidence**, never a fabricated
  owner, plus two concrete resolutions (label the key once, or isolate a shared key).
- **Budget:** human-declared; it warns as you approach and pages when you exceed.

It observes and explains spend. It never throttles, pauses, or spends.
