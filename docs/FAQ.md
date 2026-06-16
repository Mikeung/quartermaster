# FAQ

**Will it change or break anything?**
No. Quartermaster is read-only and advisory. It never deploys, restarts, scales, or
remediates. The only paths it writes to are its own `data/` (a local SQLite store)
and `reports/` (generated markdown).

**What does it read?**
Process and socket lists (`ps`, `ss`, `lsof`), systemd and Docker state, the git
repositories you point it at, the kernel log, and the *permissions* of `.env` files
(not their contents). It needs only read access.

**What leaves the box?**
Nothing, unless you opt in. Telegram alerts, optional LLM-assisted drafting, and the
cost advisor's provider-account-usage lookups are all off by default and each require
a key you supply.

**Does it need root?**
No. Without elevated read access some host checks simply become no-ops rather than
failing.

**Is it only for AI agents?**
No — it explains any Linux service. But it's *built* for someone overseeing a fleet
of agents/automations: per-agent cost attribution, runaway/budget alerts, and
agent activity findings are first-class.

**Does it replace my monitoring (Prometheus, Grafana, etc.)?**
No, it complements them. Dashboards tell you a metric moved. Quartermaster tells you
*what the thing is, which agent owns it, why it exists, and what depends on it* —
the context dashboards don't carry.

**Which LLM does it need?**
None to run. Discovery, topology, cost accounting, incidents, and reports are all
deterministic and work with no LLM at all. A couple of optional features use a
provider key you supply; they degrade gracefully when it's absent.

**How does cost attribution work without me tagging everything?**
By evidence already on the box: a provider key that maps 1:1 to an agent (you label
it once), or an agent's own logged usage. Anything it can't attribute is shown
honestly as "Unattributed" with an investigation — it never invents an owner.

**What OS does it support?**
Linux-first. The scanners shell out to standard Linux tools and degrade where they're
absent.

**How do I trust the numbers?**
Every claim carries a confidence level and the evidence behind it, and the engine is
deterministic. Spend figures are tagged by source (provider account vs. self-reported)
so you always know how authoritative a number is.

**Is it safe to run in production?**
That's the design center: because it can only read and never acts, the worst case is
a read. See [SECURITY.md](../SECURITY.md) for the full list of what it touches.
