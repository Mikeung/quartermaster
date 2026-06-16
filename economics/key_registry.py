"""Key→agent labels — operator-declared, human_declared, sticky.

Providers expose usage per API key. When an operator knows a given key belongs
to one agent, they LABEL it once (a one-time tag — NOT a new key). That label
binds the key's spend to a graph node and is human_declared: reconciliation must
never overwrite it (the graph_store sticky invariant enforces this).

This module is pure: it parses the operator's declarations (config/cost_advisor.yml)
and resolves a key_id → its declared owner. No secret value ever appears here —
a key is identified by the provider's key_id and/or a last-4 key_hint.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class KeyLabel:
    """An operator's one-time tag: this provider key belongs to this agent."""

    provider: str
    key_id: str          # provider's key/workspace id (matched against usage)
    key_hint: str        # last-4 hint, for human recognition (never the secret)
    agent: str           # graph builder_node_id, e.g. "repo:lesia"
    agent_target: str    # graph target for that node, e.g. "/srv/lesia"
    shared: bool         # True → key serves multiple agents (cannot attribute 1:1)
    evidence: str

    def matches(self, provider: str, key_id: str) -> bool:
        if self.provider.lower() != provider.lower():
            return False
        kid = (key_id or "").strip()
        return bool(kid) and (kid == self.key_id or kid.endswith(self.key_hint.lstrip("…")))


def key_node_id(provider: str, key_id: str) -> str:
    """builder_node_id for a provider key node (lives on target 'external')."""
    return f"key:{provider.lower()}:{key_id}"


def load_key_labels(path: str | Path) -> tuple[list[KeyLabel], list[str]]:
    """Parse key labels from the operator config. Returns (labels, errors).

    Never raises on a missing file or a malformed entry — a malformed entry is
    skipped and named in errors, so a typo can never silently drop attribution.
    """
    p = Path(path)
    if not p.exists():
        return [], []
    try:
        doc = yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError as exc:
        return [], [f"cost_advisor.yml parse error: {exc}"]

    labels: list[KeyLabel] = []
    errors: list[str] = []
    for i, raw in enumerate(doc.get("keys") or []):
        if not isinstance(raw, dict):
            errors.append(f"keys[{i}]: not a mapping")
            continue
        provider = str(raw.get("provider") or "").strip().lower()
        key_id = str(raw.get("key_id") or "").strip()
        agent = str(raw.get("agent") or "").strip()
        if not (provider and key_id and agent):
            errors.append(f"keys[{i}]: provider, key_id and agent are all required")
            continue
        labels.append(KeyLabel(
            provider=provider,
            key_id=key_id,
            key_hint=str(raw.get("key_hint") or "").strip(),
            agent=agent,
            agent_target=str(raw.get("agent_target") or "").strip(),
            shared=bool(raw.get("shared", False)),
            evidence=str(raw.get("evidence") or "operator-declared").strip(),
        ))
    return labels, errors


def resolve_key_owner(provider: str, key_id: str, labels: list[KeyLabel]) -> KeyLabel | None:
    """Return the operator's label for this key, or None if unlabelled.

    A shared key resolves to its label too (so the caller can see it is shared
    and decline a 1:1 attribution) — the caller decides; this never guesses.
    """
    for lbl in labels:
        if lbl.matches(provider, key_id):
            return lbl
    return None


def load_budget(path: str | Path) -> dict[str, Any]:
    """The human-declared budget block, or {} when none is declared.

    Shape: {"period": "monthly"|"daily", "limit_usd": float, "scope": "all"|provider}.
    Budget is owner-owned; the advisor never invents the number.
    """
    p = Path(path)
    if not p.exists():
        return {}
    try:
        doc = yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError:
        return {}
    budget = doc.get("budget")
    if not isinstance(budget, dict):
        return {}
    try:
        limit = float(budget.get("limit_usd") or 0)
    except (TypeError, ValueError):
        return {}
    if limit <= 0:
        return {}
    return {
        "period": str(budget.get("period") or "monthly"),
        "limit_usd": limit,
        "scope": str(budget.get("scope") or "all"),
    }
