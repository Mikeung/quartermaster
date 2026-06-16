
from cognition.temporal_analysis import (
    TemporalAnalysisEngine,
    _compare_snapshots,
    _compute_volatility,
)


def _make_snapshot(
    snap_id: int,
    created_at: str,
    llm_providers: list[str] | None = None,
    frameworks: list[str] | None = None,
    llm_sdks: list[str] | None = None,
    docker: bool = False,
    workflows: list[str] | None = None,
) -> dict:
    return {
        "id": snap_id,
        "created_at": created_at,
        "data": {
            "target": "/test",
            "llm_detections": [{"provider": p} for p in (llm_providers or [])],
            "scanner_results": {
                "results": {
                    "repo_scanner": {
                        "frameworks": frameworks or [],
                        "llm_sdks": llm_sdks or [],
                        "docker": {"present": docker},
                        "ci_cd": [],
                        "primary_language": "Python",
                    }
                }
            },
            "workflows": [{"workflow_type": wt, "name": wt} for wt in (workflows or [])],
        },
    }


def test_empty_snapshots_returns_safe_analysis():
    result = TemporalAnalysisEngine().analyze([], window_days=7)
    assert result.snapshot_count == 0
    assert result.volatility_score == 0.0
    assert result.stability_score == 1.0
    assert result.total_changes == 0


def test_single_snapshot_no_changes():
    snap = _make_snapshot(1, "2026-05-16 10:00:00", llm_providers=["anthropic"])
    result = TemporalAnalysisEngine().analyze([snap], window_days=7)
    assert result.snapshot_count == 1
    assert result.total_changes == 0
    assert result.volatility_score == 0.0


def test_two_snapshots_provider_added():
    a = _make_snapshot(1, "2026-05-15 10:00:00", llm_providers=[])
    b = _make_snapshot(2, "2026-05-16 10:00:00", llm_providers=["anthropic"])
    result = TemporalAnalysisEngine().analyze([a, b])
    assert result.total_changes == 1
    assert result.change_events[0].change_type == "llm_provider_added"
    assert result.change_events[0].value == "anthropic"


def test_two_snapshots_provider_removed():
    a = _make_snapshot(1, "2026-05-15 10:00:00", llm_providers=["openai"])
    b = _make_snapshot(2, "2026-05-16 10:00:00", llm_providers=[])
    result = TemporalAnalysisEngine().analyze([a, b])
    types = [e.change_type for e in result.change_events]
    assert "llm_provider_removed" in types


def test_framework_churn_detected():
    a = _make_snapshot(1, "2026-05-14 10:00:00", frameworks=["fastapi"])
    b = _make_snapshot(2, "2026-05-15 10:00:00", frameworks=["flask"])
    c = _make_snapshot(3, "2026-05-16 10:00:00", frameworks=["fastapi"])
    result = TemporalAnalysisEngine().analyze([a, b, c])
    assert result.total_changes >= 4  # fastapi removed, flask added, flask removed, fastapi added


def test_volatility_score_bounded():
    snaps = [
        _make_snapshot(i, f"2026-05-1{i} 10:00:00", llm_providers=["anthropic" if i % 2 == 0 else "openai"])
        for i in range(1, 8)
    ]
    result = TemporalAnalysisEngine().analyze(snaps)
    assert 0.0 <= result.volatility_score <= 1.0
    assert abs(result.volatility_score + result.stability_score - 1.0) < 0.001


def test_churning_components_identified():
    a = _make_snapshot(1, "2026-05-14 10:00:00", llm_providers=["openai"])
    b = _make_snapshot(2, "2026-05-15 10:00:00", llm_providers=[])
    c = _make_snapshot(3, "2026-05-16 10:00:00", llm_providers=["openai"])
    result = TemporalAnalysisEngine().analyze([a, b, c])
    assert any(ch.component == "openai" for ch in result.churning_components)
    openai_churn = next(ch for ch in result.churning_components if ch.component == "openai")
    assert openai_churn.change_count == 2


def test_stable_system_no_churn_indicators():
    snaps = [
        _make_snapshot(i, f"2026-05-1{i} 10:00:00", llm_providers=["anthropic"], frameworks=["fastapi"])
        for i in range(1, 4)
    ]
    result = TemporalAnalysisEngine().analyze(snaps)
    assert result.volatility_score == 0.0
    assert any("stable" in ind.lower() for ind in result.churn_indicators)


def test_compare_snapshots_docker_change():
    older = _make_snapshot(1, "2026-05-15 10:00:00", docker=False)
    newer = _make_snapshot(2, "2026-05-16 10:00:00", docker=True)
    events = _compare_snapshots(older, newer)
    assert any(e.change_type == "docker_added" for e in events)


def test_workflow_type_change_detected():
    a = _make_snapshot(1, "2026-05-15 10:00:00", workflows=[])
    b = _make_snapshot(2, "2026-05-16 10:00:00", workflows=["rag_pipeline"])
    events = _compare_snapshots(a, b)
    assert any(e.change_type == "workflow_type_added" and e.value == "rag_pipeline" for e in events)


def test_compute_volatility_zero_changes():
    assert _compute_volatility(0, 3, 5) == 0.0


def test_compute_volatility_capped_at_one():
    assert _compute_volatility(1000, 1, 5) == 1.0


def test_to_dict_serializable():
    snaps = [
        _make_snapshot(1, "2026-05-15 10:00:00", llm_providers=[]),
        _make_snapshot(2, "2026-05-16 10:00:00", llm_providers=["anthropic"]),
    ]
    result = TemporalAnalysisEngine().analyze(snaps)
    d = result.to_dict()
    assert "volatility_score" in d
    assert "change_events" in d
    assert isinstance(d["change_events"], list)
    assert "churning_components" in d
