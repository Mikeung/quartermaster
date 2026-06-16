"""Tests for cognition/heuristics.py — HeuristicRegistry."""

from __future__ import annotations

import pytest

from cognition.heuristics import Heuristic, HeuristicRegistry


class TestHeuristicRegistry:
    def test_get_known_heuristic(self):
        reg = HeuristicRegistry()
        h = reg.get("severity_high_score")
        assert isinstance(h, Heuristic)
        assert h.name == "severity_high_score"
        assert h.threshold == 0.60

    def test_get_unknown_raises(self):
        reg = HeuristicRegistry()
        with pytest.raises(KeyError):
            reg.get("not_a_real_heuristic")

    def test_threshold_returns_float(self):
        reg = HeuristicRegistry()
        val = reg.threshold("attention_suppress_threshold")
        assert isinstance(val, float)
        assert val == 0.35

    def test_all_returns_sorted_list(self):
        reg = HeuristicRegistry()
        heuristics = reg.all()
        assert len(heuristics) > 10
        names = [h.name for h in heuristics]
        assert names == sorted(names)

    def test_by_module(self):
        reg = HeuristicRegistry()
        sev_heuristics = reg.by_module("cognition.severity")
        assert len(sev_heuristics) > 0
        assert all(h.source_module == "cognition.severity" for h in sev_heuristics)

    def test_to_dict_structure(self):
        reg = HeuristicRegistry()
        d = reg.to_dict()
        assert "heuristics" in d
        assert "count" in d
        assert "advisory" in d
        assert d["count"] == len(reg.all())

    def test_heuristic_to_dict(self):
        reg = HeuristicRegistry()
        h = reg.get("high_volatility_threshold")
        d = h.to_dict()
        assert "name" in d
        assert "description" in d
        assert "threshold" in d
        assert "rationale" in d
        assert "source_module" in d

    def test_all_have_rationale(self):
        reg = HeuristicRegistry()
        for h in reg.all():
            assert len(h.rationale) > 0, f"Heuristic {h.name} has no rationale"

    def test_all_have_source_module(self):
        reg = HeuristicRegistry()
        for h in reg.all():
            assert "cognition" in h.source_module or "reports" in h.source_module, \
                f"Heuristic {h.name} has unexpected source_module: {h.source_module}"

    def test_severity_thresholds_ordered(self):
        reg = HeuristicRegistry()
        low = reg.threshold("severity_low_score")
        moderate = reg.threshold("severity_moderate_score")
        high = reg.threshold("severity_high_score")
        critical = reg.threshold("severity_critical_score")
        assert low < moderate < high < critical

    def test_cluster_thresholds_ordered(self):
        reg = HeuristicRegistry()
        minimum = reg.threshold("cluster_minimum_score")
        high_score = reg.threshold("cluster_high_score")
        assert minimum < high_score
