"""Cost advisor core — whole view, attribution by evidence, budget, determinism."""

from __future__ import annotations

from datetime import UTC, datetime

from cognition import cost_advisor
from economics.key_registry import KeyLabel
from economics.provider_usage import ProviderUsageRecord, ProviderUsageResult

_NOW = datetime(2026, 6, 15, tzinfo=UTC)


def _ledger(by_provider, by_project, by_day=None):
    return {
        "total_cost": sum(p["cost_usd"] for p in by_provider),
        "by_provider": by_provider, "by_project": by_project,
        "by_day": by_day or [],
    }


class TestLedgerMode:
    """No provider account usage → attribute by the self-reported ledger."""

    def _advisory(self):
        ledger = _ledger(
            by_provider=[{"provider": "google", "cost_usd": 100.21, "event_count": 15}],
            by_project=[
                {"project_id": "lesia", "cost_usd": 90.21, "event_count": 12,
                 "first_ts": "2026-06-14T00:00:00Z", "last_ts": "2026-06-15T00:00:00Z"},
                {"project_id": "", "cost_usd": 10.00, "event_count": 3,
                 "first_ts": "2026-06-14T01:00:00Z", "last_ts": "2026-06-14T02:00:00Z"},
            ],
        )
        usage = {"google": ProviderUsageResult("google", available=False, reason="unsupported")}
        return cost_advisor.build_advisory(
            provider_usage=usage, ledger=ledger, now=_NOW,
        )

    def test_whole_view_total_and_source(self):
        adv = self._advisory()
        assert round(adv["whole_view"]["total_usd"], 2) == 100.21
        prov = adv["whole_view"]["providers"][0]
        assert prov["source"] == "self_reported_ledger"
        assert prov["confidence"] == "Medium"

    def test_attributed_agent_self_logged(self):
        adv = self._advisory()
        attributed = adv["attribution"]["attributed"]
        lesia = next(a for a in attributed if a["agent"] == "lesia")
        assert lesia["basis"] == "agent_self_logged"
        assert lesia["agent_node"] == "repo:lesia"
        assert round(lesia["cost_usd"], 2) == 90.21

    def test_unattributed_bucket_and_finding(self):
        adv = self._advisory()
        unattr = adv["attribution"]["unattributed"]
        assert len(unattr) == 1
        assert round(unattr[0]["cost_usd"], 2) == 10.0
        # the $10 bucket exceeds the investigate threshold → a money finding
        types = [f["finding_type"] for f in adv["findings"]]
        assert "unknown_cost_owner" in types

    def test_deterministic(self):
        assert self._advisory() == self._advisory()


class TestAccountUsageMode:
    """Provider account usage with per-key split → attribute by 1:1 key labels."""

    def _usage(self):
        recs = [
            ProviderUsageRecord("anthropic", "apikey_lesia", "…a1b2", "2026-06-14", 50.0),
            ProviderUsageRecord("anthropic", "apikey_shared", "…c3d4", "2026-06-14", 20.0),
            ProviderUsageRecord("anthropic", "apikey_mystery", "…e5f6", "2026-06-14", 8.0),
        ]
        return {"anthropic": ProviderUsageResult("anthropic", available=True, records=recs)}

    def _labels(self):
        return [
            KeyLabel("anthropic", "apikey_lesia", "a1b2", "repo:lesia", "/srv/lesia", False, "ev"),
            KeyLabel("anthropic", "apikey_shared", "c3d4", "repo:seo-agent", "/srv/seo-agent", True, "shared"),
        ]

    def _advisory(self):
        ledger = _ledger(by_provider=[], by_project=[])
        return cost_advisor.build_advisory(
            provider_usage=self._usage(), ledger=ledger, key_labels=self._labels(), now=_NOW,
        )

    def test_1to1_key_attributed(self):
        adv = self._advisory()
        lesia = next(a for a in adv["attribution"]["attributed"] if a["agent"] == "repo:lesia")
        assert lesia["basis"] == "key_1to1" and lesia["confidence"] == "High"
        assert round(lesia["cost_usd"], 2) == 50.0

    def test_shared_key_is_unattributed_with_reason(self):
        adv = self._advisory()
        shared = next(u for u in adv["attribution"]["unattributed"] if u["key_id"] == "apikey_shared")
        assert "shared" in shared["reason"].lower()
        assert shared["shared_label"] == "repo:seo-agent"

    def test_unlabelled_key_is_unattributed(self):
        adv = self._advisory()
        mystery = next(u for u in adv["attribution"]["unattributed"] if u["key_id"] == "apikey_mystery")
        assert "unlabelled" in mystery["reason"].lower()

    def test_provider_source_high_confidence(self):
        adv = self._advisory()
        assert adv["whole_view"]["providers"][0]["source"] == "provider_account_usage"
        assert adv["whole_view"]["providers"][0]["confidence"] == "High"


class TestBudget:
    def _adv(self, limit, spend):
        ledger = _ledger(by_provider=[{"provider": "google", "cost_usd": spend, "event_count": 1}],
                         by_project=[{"project_id": "lesia", "cost_usd": spend, "event_count": 1,
                                      "first_ts": None, "last_ts": None}])
        usage = {"google": ProviderUsageResult("google", available=False, reason="x")}
        return cost_advisor.build_advisory(
            provider_usage=usage, ledger=ledger,
            budget={"period": "monthly", "limit_usd": limit, "scope": "all"},
            budget_spend_usd=spend, now=_NOW,
        )

    def test_approaching_warns(self):
        adv = self._adv(100.0, 85.0)
        assert adv["budget"]["state"] == "approaching"
        assert any(f["finding_type"] == "budget_approaching" for f in adv["findings"])

    def test_exceeded_is_money_critical(self):
        adv = self._adv(100.0, 130.0)
        assert adv["budget"]["state"] == "exceeded"
        assert any(f["finding_type"] == "budget_exceeded" for f in adv["findings"])

    def test_ok_no_finding(self):
        adv = self._adv(100.0, 20.0)
        assert adv["budget"]["state"] == "ok"
        assert not any(f["finding_type"].startswith("budget_") for f in adv["findings"])

    def test_not_declared_inactive(self):
        ledger = _ledger(by_provider=[], by_project=[])
        adv = cost_advisor.build_advisory(provider_usage={}, ledger=ledger, now=_NOW)
        assert adv["budget"]["state"] == "inactive"


class TestTrend:
    def test_rising(self):
        ledger = _ledger(
            by_provider=[{"provider": "google", "cost_usd": 50.0, "event_count": 1}],
            by_project=[{"project_id": "lesia", "cost_usd": 50.0, "event_count": 1,
                         "first_ts": None, "last_ts": None}],
            by_day=[{"day": "2026-06-13", "cost_usd": 10.0},
                    {"day": "2026-06-14", "cost_usd": 12.0},
                    {"day": "2026-06-15", "cost_usd": 50.0}],
        )
        usage = {"google": ProviderUsageResult("google", available=False, reason="x")}
        adv = cost_advisor.build_advisory(provider_usage=usage, ledger=ledger, now=_NOW)
        assert adv["trend"]["direction"] == "rising"
