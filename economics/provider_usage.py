"""Provider account-usage reader — the headline spend view.

Pulls TOTAL spend per provider straight from the provider's own account-usage
API. This is the authoritative number (what the provider will bill), distinct
from the self-reported ledger (what an agent logged about itself).

Hard rules this module obeys:
  - The usage-scoped key is read from an env VAR NAME (config) ONLY. Its value
    is never logged, never returned, never stored in a record. Only a key_hint
    (last 4 chars) ever leaves this module.
  - Opt-in. No env var set → the provider's view degrades to available=False
    with a plain reason; the advisor falls back to the ledger for that provider.
  - It NEVER raises. Any network/parse error is caught and returned as an
    unavailable result with a sanitised reason (the key is scrubbed from it).
  - Read-only. GET only. It never changes spend or touches anything billable.

The HTTP fetcher is injectable so the normalisation is fully testable without
network or a real key. The default fetcher uses urllib (no new dependency).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from config import observability_config as cfg

# A fetcher takes (url, headers, timeout_s) and returns the response body text.
# Injected in tests; the default hits the network read-only.
Fetcher = Callable[[str, dict[str, str], float], str]


@dataclass(frozen=True)
class ProviderUsageRecord:
    """One normalised account-usage row: a provider's spend for a key/day.

    key_id is the provider's own identifier for the API key/workspace (NOT the
    secret). key_hint is the last 4 chars only. The secret value never appears.
    """

    provider: str
    key_id: str          # provider key/workspace id, or "" when the API can't split by key
    key_hint: str        # last-4 only (e.g. "…a1b2"), never the secret
    day: str             # YYYY-MM-DD (UTC)
    cost_usd: float
    calls: int = 0
    models: tuple[str, ...] = ()
    source: str = "provider_account_usage"

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "key_id": self.key_id,
            "key_hint": self.key_hint,
            "day": self.day,
            "cost_usd": round(self.cost_usd, 4),
            "calls": self.calls,
            "models": list(self.models),
            "source": self.source,
        }


@dataclass
class ProviderUsageResult:
    """The outcome of reading one provider's account usage.

    available=False means we could not read the authoritative provider total —
    the reason says why, and the advisor falls back to the ledger.
    """

    provider: str
    available: bool
    reason: str = ""                 # populated when available is False
    records: list[ProviderUsageRecord] = field(default_factory=list)

    @property
    def total_cost(self) -> float:
        return round(sum(r.cost_usd for r in self.records), 4)

    @property
    def per_key(self) -> dict[str, float]:
        """Spend keyed by the provider's key_id (only when the API splits by key)."""
        out: dict[str, float] = {}
        for r in self.records:
            if r.key_id:
                out[r.key_id] = round(out.get(r.key_id, 0.0) + r.cost_usd, 4)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "available": self.available,
            "reason": self.reason,
            "total_cost": self.total_cost,
            "per_key": self.per_key,
            "records": [r.to_dict() for r in self.records],
        }


# ---------------------------------------------------------------------------
# Key resolution — env-only, never logged
# ---------------------------------------------------------------------------

def _key_hint(secret: str) -> str:
    """Last-4 fingerprint of a key. Never returns the key itself."""
    s = secret.strip()
    return f"…{s[-4:]}" if len(s) >= 4 else "…"


def _scrub(text: str, secret: str | None) -> str:
    """Remove any occurrence of the secret from a message before it is surfaced."""
    if secret:
        text = text.replace(secret, "<redacted>")
    return text


def _default_fetcher(url: str, headers: dict[str, str], timeout_s: float) -> str:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        body: str = resp.read().decode("utf-8")
    return body


# ---------------------------------------------------------------------------
# Per-provider normalisers (deterministic; given a response body → records)
# ---------------------------------------------------------------------------

def _normalise_anthropic(body: str, key_hint: str) -> list[ProviderUsageRecord]:
    """Anthropic Admin cost report → records. Tolerant of shape drift.

    Expects a paginated cost report whose buckets carry a start day and cost
    amounts, optionally broken out by api_key/workspace. Unknown shape → [].
    """
    data = json.loads(body)
    records: list[ProviderUsageRecord] = []
    for bucket in data.get("data", []) or []:
        day = str(bucket.get("starting_at") or bucket.get("date") or "")[:10]
        results = bucket.get("results") or bucket.get("cost") or []
        if isinstance(results, dict):
            results = [results]
        for r in results:
            amount = r.get("amount") or r.get("cost") or r.get("amount_usd") or 0.0
            cost = _to_float(amount)
            key_id = str(r.get("api_key_id") or r.get("workspace_id") or "")
            model = r.get("model")
            records.append(ProviderUsageRecord(
                provider="anthropic", key_id=key_id, key_hint=key_hint, day=day,
                cost_usd=cost, calls=int(_to_float(r.get("calls") or 0)),
                models=(str(model),) if model else (),
            ))
    return records


def _normalise_openai(body: str, key_hint: str) -> list[ProviderUsageRecord]:
    """OpenAI organization costs → records. Tolerant of shape drift."""
    data = json.loads(body)
    records: list[ProviderUsageRecord] = []
    for bucket in data.get("data", []) or []:
        day = _epoch_day(bucket.get("start_time")) or str(bucket.get("date") or "")[:10]
        for r in bucket.get("results", []) or []:
            amount = r.get("amount") or {}
            cost = _to_float(amount.get("value") if isinstance(amount, dict) else amount)
            key_id = str(r.get("api_key_id") or r.get("project_id") or "")
            records.append(ProviderUsageRecord(
                provider="openai", key_id=key_id, key_hint=key_hint, day=day,
                cost_usd=cost,
            ))
    return records


_NORMALISERS: dict[str, Callable[[str, str], list[ProviderUsageRecord]]] = {
    "anthropic": _normalise_anthropic,
    "openai": _normalise_openai,
}

# Account-usage endpoint per provider (GET, read-only). Date params appended.
_USAGE_URL: dict[str, str] = {
    "anthropic": "https://api.anthropic.com/v1/organizations/cost_report",
    "openai": "https://api.openai.com/v1/organization/costs",
}


def _headers(provider: str, secret: str) -> dict[str, str]:
    if provider == "anthropic":
        return {"x-api-key": secret, "anthropic-version": "2023-06-01"}
    return {"Authorization": f"Bearer {secret}"}


def _to_float(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _epoch_day(x: Any) -> str:
    """OpenAI buckets carry a unix start_time; render the UTC day."""
    try:
        from datetime import UTC, datetime
        return datetime.fromtimestamp(int(x), tz=UTC).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return ""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def read_provider_usage(
    provider: str,
    *,
    start_day: str,
    end_day: str,
    fetcher: Fetcher | None = None,
    env: dict[str, str] | None = None,
) -> ProviderUsageResult:
    """Read one provider's account usage between start_day and end_day (YYYY-MM-DD).

    Degrades — never raises:
      - provider has no account-usage cost API the advisor reads → unavailable
      - the env var holding the usage-scoped key is unset/empty → unavailable
      - any network/parse error → unavailable (key scrubbed from the reason)
    """
    provider = provider.lower()
    env = env if env is not None else dict(os.environ)

    if provider in cfg.PROVIDER_USAGE_UNSUPPORTED or provider not in _USAGE_URL:
        return ProviderUsageResult(
            provider, available=False,
            reason=f"{provider}: no per-key account-usage cost API — using self-reported ledger",
        )

    env_var = cfg.PROVIDER_USAGE_KEY_ENV.get(provider, "")
    secret = (env.get(env_var) or "").strip()
    if not secret:
        return ProviderUsageResult(
            provider, available=False,
            reason=f"{provider}: no usage-scoped key configured (env {env_var} unset) — using self-reported ledger",
        )

    hint = _key_hint(secret)
    fetch = fetcher or _default_fetcher
    url = f"{_USAGE_URL[provider]}?start_date={start_day}&end_date={end_day}"
    try:
        body = fetch(url, _headers(provider, secret), cfg.PROVIDER_USAGE_TIMEOUT_S)
        records = _NORMALISERS[provider](body, hint)
        return ProviderUsageResult(provider, available=True, records=records)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        return ProviderUsageResult(
            provider, available=False,
            reason=f"{provider}: account-usage read failed ({_scrub(str(exc), secret)})",
        )
    except (ValueError, KeyError, TypeError) as exc:
        return ProviderUsageResult(
            provider, available=False,
            reason=f"{provider}: account-usage response not understood ({_scrub(str(exc), secret)})",
        )


def read_all_provider_usage(
    providers: tuple[str, ...] = cfg.SUPPORTED_PROVIDERS,
    *,
    start_day: str,
    end_day: str,
    fetcher: Fetcher | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, ProviderUsageResult]:
    """Read account usage for each provider. De-dups google/gemini aliases."""
    seen: set[str] = set()
    out: dict[str, ProviderUsageResult] = {}
    for p in providers:
        p = p.lower()
        if p in seen:
            continue
        seen.add(p)
        out[p] = read_provider_usage(
            p, start_day=start_day, end_day=end_day, fetcher=fetcher, env=env,
        )
    return out
