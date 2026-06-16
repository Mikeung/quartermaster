"""Economics — the cost advisor (agent API-spend advisor).

Fills the Economics slot: it pulls total spend per provider from provider
account usage, attributes it to agents by evidence already on the box, and
surfaces everything else honestly as "Unattributed" — with an investigation.

Same philosophy as the rest of the system: deterministic, evidence-cited,
advisory-only. It observes and explains spend; it never throttles, pauses, or
spends. Opt-in. It never raises — every collector degrades to a stated reason.

Layout:
  provider_usage.py     — read provider account usage (env-only key, never logged)
  connection_evidence.py — read-only on-box outbound connections (who's calling whom)
  key_registry.py       — operator-declared key→agent labels (human_declared, sticky)

The deterministic reasoning lives in cognition/cost_advisor.py and
cognition/cost_investigation.py; rendering in reports/cost_advisor_report.py.
"""
