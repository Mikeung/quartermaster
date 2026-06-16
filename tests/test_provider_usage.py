"""Provider account-usage reader — opt-in, env-only, key-safe, never raises."""

from __future__ import annotations

import json

from economics import provider_usage as pu

_ANTHROPIC_BODY = json.dumps({
    "data": [
        {"starting_at": "2026-06-14T00:00:00Z",
         "results": [{"api_key_id": "apikey_lesia", "amount": "12.50", "model": "claude-sonnet-4"}]},
        {"starting_at": "2026-06-15T00:00:00Z",
         "results": [{"api_key_id": "apikey_lesia", "amount": "3.00"},
                     {"api_key_id": "apikey_unknown", "amount": "7.25"}]},
    ]
})

_SECRET = "ADMIN-KEY-not-a-real-secret-abcd"


def _fetcher(body):
    def _f(url, headers, timeout):
        return body
    return _f


class TestDegrade:
    def test_no_key_is_unavailable_with_named_env_var(self):
        res = pu.read_provider_usage("anthropic", start_day="2026-06-01", end_day="2026-06-15", env={})
        assert res.available is False
        assert "ANTHROPIC_ADMIN_KEY" in res.reason
        assert res.records == []

    def test_unsupported_provider_degrades(self):
        res = pu.read_provider_usage("google", start_day="2026-06-01", end_day="2026-06-15",
                                     env={"ANTHROPIC_ADMIN_KEY": "x"})
        assert res.available is False
        assert "no per-key account-usage" in res.reason

    def test_network_error_never_raises_and_scrubs_key(self):
        def boom(url, headers, timeout):
            raise OSError(f"connection failed using {_SECRET}")
        res = pu.read_provider_usage(
            "anthropic", start_day="2026-06-01", end_day="2026-06-15",
            fetcher=boom, env={"ANTHROPIC_ADMIN_KEY": _SECRET},
        )
        assert res.available is False
        assert _SECRET not in res.reason
        assert "<redacted>" in res.reason

    def test_bad_json_is_unavailable_not_raised(self):
        res = pu.read_provider_usage(
            "anthropic", start_day="2026-06-01", end_day="2026-06-15",
            fetcher=_fetcher("not json"), env={"ANTHROPIC_ADMIN_KEY": _SECRET},
        )
        assert res.available is False
        assert "not understood" in res.reason


class TestNormalise:
    def _res(self):
        return pu.read_provider_usage(
            "anthropic", start_day="2026-06-01", end_day="2026-06-15",
            fetcher=_fetcher(_ANTHROPIC_BODY), env={"ANTHROPIC_ADMIN_KEY": _SECRET},
        )

    def test_records_and_totals(self):
        res = self._res()
        assert res.available is True
        assert round(res.total_cost, 2) == 22.75
        assert round(res.per_key["apikey_lesia"], 2) == 15.50
        assert round(res.per_key["apikey_unknown"], 2) == 7.25

    def test_key_hint_is_last4_only_and_secret_never_leaks(self):
        res = self._res()
        blob = json.dumps(res.to_dict())
        assert _SECRET not in blob
        for r in res.records:
            assert r.key_hint == "…abcd"
            assert _SECRET not in json.dumps(r.to_dict())

    def test_deterministic(self):
        assert self._res().to_dict() == self._res().to_dict()
