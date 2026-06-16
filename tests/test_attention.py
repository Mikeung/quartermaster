
from cognition.attention import AttentionGuidance, AttentionReport
from cognition.temporal_analysis import TemporalAnalysis


def _empty_temporal() -> TemporalAnalysis:
    return TemporalAnalysis(
        window_days=7,
        snapshot_count=2,
        first_snapshot_at="2026-05-15",
        last_snapshot_at="2026-05-16",
        total_changes=0,
        change_events=[],
        change_frequency={},
        churning_components=[],
        volatility_score=0.0,
        stability_score=1.0,
        churn_indicators=["System is stable"],
        trend_observations=[],
    )


def _make_priority_item(
    urgency: str = "high",
    score: float = 0.70,
    category: str = "topology",
    title: str = "Test concern",
) -> dict:
    from cognition.prioritization import PriorityItem
    return PriorityItem(
        rank=1,
        urgency=urgency,
        priority_score=score,
        title=title,
        summary="A test summary",
        category=category,
        evidence=["Evidence A"],
        reasoning=["base score 0.70"],
    )


def test_empty_inputs_returns_report_with_no_concerns():
    report = AttentionGuidance().generate([], _empty_temporal(), [])
    assert isinstance(report, AttentionReport)
    assert len(report.top_concerns) == 0
    assert "stable" in report.attention_summary.lower() or "no significant" in report.attention_summary.lower()


def test_high_score_items_surface_as_concerns():
    items = [_make_priority_item(urgency="critical", score=0.85)]
    report = AttentionGuidance().generate(items, _empty_temporal(), [])
    assert len(report.top_concerns) >= 1
    assert report.top_concerns[0].urgency == "critical"


def test_low_score_items_suppressed():
    low_items = [_make_priority_item(urgency="informational", score=0.15)]
    report = AttentionGuidance().generate(low_items, _empty_temporal(), [])
    assert report.suppressed_count >= 1
    assert len(report.top_concerns) == 0


def test_cost_items_appear_in_cost_concerns():
    items = [_make_priority_item(urgency="high", score=0.70, category="cost", title="Cost risk")]
    report = AttentionGuidance().generate(items, _empty_temporal(), [])
    assert any(i.category == "cost" for i in report.cost_concerns)


def test_stability_items_appear_in_stability_concerns():
    items = [_make_priority_item(urgency="high", score=0.65, category="stability")]
    report = AttentionGuidance().generate(items, _empty_temporal(), [])
    assert any(i.category == "stability" for i in report.stability_concerns)


def test_drift_concerns_from_volatile_temporal():
    temporal = _empty_temporal()
    temporal.volatility_score = 0.70
    temporal.churn_indicators = [
        "'anthropic' changed 3 times in window",
        "High change rate: 9 changes across 3 transitions",
    ]
    report = AttentionGuidance().generate([], temporal, [])
    assert len(report.drift_concerns) >= 1


def test_top_concerns_capped_at_max():
    items = [_make_priority_item(score=0.80) for _ in range(10)]
    report = AttentionGuidance().generate(items, _empty_temporal(), [])
    assert len(report.top_concerns) <= 5


def test_attention_summary_non_empty():
    items = [_make_priority_item(urgency="critical", score=0.85)]
    report = AttentionGuidance().generate(items, _empty_temporal(), [])
    assert len(report.attention_summary) > 0


def test_to_dict_serializable():
    items = [_make_priority_item(urgency="high", score=0.70)]
    report = AttentionGuidance().generate(items, _empty_temporal(), [])
    d = report.to_dict()
    assert "top_concerns" in d
    assert "suppressed_count" in d
    assert "attention_summary" in d
    assert isinstance(d["top_concerns"], list)


def test_generated_at_present():
    report = AttentionGuidance().generate([], _empty_temporal(), [])
    assert report.generated_at
    assert "2026" in report.generated_at or "T" in report.generated_at
