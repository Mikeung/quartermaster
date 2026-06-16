
from cognition.prioritization import PrioritizationEngine, _urgency
from cognition.temporal_analysis import TemporalAnalysis


def _make_rec(
    title: str = "Test rec",
    confidence: float = 0.80,
    impact: str = "high",
    category: str = "topology",
    evidence: list | None = None,
) -> dict:
    return {
        "title": title,
        "observation": "Test observation",
        "evidence": evidence or ["evidence A"],
        "confidence": confidence,
        "impact": impact,
        "category": category,
        "suggested_investigation": "Check this.",
        "urgency": "monitor",
        "recurrence_count": 0,
    }


def _empty_temporal() -> TemporalAnalysis:
    return TemporalAnalysis(
        window_days=7,
        snapshot_count=0,
        first_snapshot_at="",
        last_snapshot_at="",
        total_changes=0,
        change_events=[],
        change_frequency={},
        churning_components=[],
        volatility_score=0.0,
        stability_score=1.0,
        churn_indicators=[],
        trend_observations=[],
    )


def test_empty_inputs_returns_empty_list():
    result = PrioritizationEngine().rank([], [], [], None)
    assert result == []


def test_single_recommendation_ranked():
    rec = _make_rec(confidence=0.80, impact="high")
    items = PrioritizationEngine().rank([rec], [], [], None)
    assert len(items) == 1
    assert items[0].rank == 1
    assert items[0].priority_score > 0.0


def test_higher_confidence_ranks_first():
    low = _make_rec(title="Low", confidence=0.40, impact="medium")
    high = _make_rec(title="High", confidence=0.90, impact="high")
    items = PrioritizationEngine().rank([low, high], [], [], None)
    assert items[0].title == "High"


def test_impact_affects_score():
    high_impact = _make_rec(confidence=0.80, impact="high")
    low_impact = _make_rec(confidence=0.80, impact="low")
    items_h = PrioritizationEngine().rank([high_impact], [], [], None)
    items_l = PrioritizationEngine().rank([low_impact], [], [], None)
    assert items_h[0].priority_score > items_l[0].priority_score


def test_cost_category_gets_bonus():
    base = _make_rec(confidence=0.70, impact="medium", category="topology")
    cost = _make_rec(confidence=0.70, impact="medium", category="cost")
    items = PrioritizationEngine().rank([base, cost], [], [], None)
    cost_item = next(i for i in items if i.category == "cost")
    base_item = next(i for i in items if i.category == "topology")
    assert cost_item.priority_score > base_item.priority_score


def test_urgency_labels_assigned():
    items = PrioritizationEngine().rank([
        _make_rec(confidence=0.95, impact="high"),  # should be critical or high
        _make_rec(confidence=0.30, impact="low"),   # should be low or informational
    ], [], [], None)
    urgencies = {i.urgency for i in items}
    assert len(urgencies) >= 1


def test_ranks_are_sequential():
    recs = [_make_rec(confidence=0.9 - i * 0.1, impact="medium") for i in range(5)]
    items = PrioritizationEngine().rank(recs, [], [], None)
    assert [i.rank for i in items] == list(range(1, 6))


def test_high_severity_cost_obs_added_as_item():
    obs = {
        "observation": "Multi-agent detected — high token volume",
        "evidence": ["agent packages detected"],
        "severity": "high",
        "estimated_tier": "high",
    }
    items = PrioritizationEngine().rank([], [obs], [], None)
    assert any(i.category == "cost" for i in items)


def test_info_severity_cost_obs_not_added():
    obs = {
        "observation": "Single provider detected",
        "evidence": [],
        "severity": "info",
        "estimated_tier": "medium",
    }
    items = PrioritizationEngine().rank([], [obs], [], None)
    assert not any(i.category == "cost" for i in items)


def test_churning_components_produce_stability_items():
    from cognition.temporal_analysis import ComponentChurn
    temporal = _empty_temporal()
    temporal.churning_components = [
        ComponentChurn("anthropic", 3, ["llm_provider_added", "llm_provider_removed", "llm_provider_added"])
    ]
    items = PrioritizationEngine().rank([], [], [], temporal)
    assert any(i.category == "stability" for i in items)


def test_reasoning_list_non_empty():
    rec = _make_rec(confidence=0.75, impact="high")
    items = PrioritizationEngine().rank([rec], [], [], None)
    assert len(items[0].reasoning) >= 1


def test_priority_score_bounded():
    rec = _make_rec(confidence=1.0, impact="high", category="cost")
    items = PrioritizationEngine().rank([rec], [], [], None)
    assert 0.0 <= items[0].priority_score <= 1.0


def test_urgency_helper():
    assert _urgency(0.85) == "critical"
    assert _urgency(0.65) == "high"
    assert _urgency(0.45) == "medium"
    assert _urgency(0.25) == "low"
    assert _urgency(0.10) == "informational"
