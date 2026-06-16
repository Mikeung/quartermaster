# Don't put an AI in charge of your AIs

Quartermaster watches a fleet of AI agents. It is not one — by design.

The thing that oversees non-deterministic workers should itself be
**deterministic, reproducible, and incapable of making things up** — because the
workers already aren't.

## Use the stupidity to strain the smarts

An LLM overseer is clever and unpredictable: exactly the wrong properties for a
watchman. Quartermaster is deliberately "dumb" — a deterministic sieve of rules,
graphs, and arithmetic over hard evidence. Dumb, but incorruptible: same inputs,
same findings, every time. You strain the clever, surprising output of your agents
through a simple, predictable mesh that **cannot be talked out of catching something.**

## Why an AI overseer is a bad idea

- **It can hallucinate** an incident — or miss a real one. Quartermaster's findings
  are derived from evidence and are reproducible; "Unknown" is a valid answer, never
  a guess.
- **It can be prompt-injected** through the very logs and agent outputs it reads. A
  regex and a dependency graph cannot be social-engineered.
- **It costs money and adds a mouth to feed** — and a new question: who watches the
  watcher? The deterministic overseer adds zero tokens.
- **It can't be audited.** "The model flagged it" is not an explanation. Every
  finding traces to the exact file, log line, or number behind it.
- **It can't be trusted near production.** Quartermaster only ever reads and
  recommends; it has no path to act, so the worst it can do is read.

## "But it mentions optional LLM features?"

Yes — and they are exactly that: **optional, contained, and never in the oversight
loop.** No finding, alert, or decision depends on an LLM. Where an optional feature
uses one (for example, drafting a plain-English description), it only proposes text
that a human confirms; it never decides what's wrong, what's urgent, or what to page
you about. The core that does the overseeing has no LLM in it.

> The watchman must not dream.
