"""Tests for memory/storage_hygiene.py — project storage profiles."""

from __future__ import annotations

from memory.storage_hygiene import (
    ProjectStorageHygiene,
    ProjectStorageProfile,
    _concentration_observations,
    _project_storage_observations,
)


def _snap_row(project_id: str, count: int, latest: str = "2026-05-17T10:00:00Z") -> dict:
    return {
        "project_id": project_id,
        "snapshot_count": count,
        "latest_at": latest,
        "oldest_at": "2026-05-01T00:00:00Z",
    }


def _event_row(project_id: str, count: int, tokens: int = 10000, cost: float = 0.01) -> dict:
    return {
        "project_id": project_id,
        "event_count": count,
        "total_tokens": tokens,
        "total_estimated_cost": cost,
        "latest_at": "2026-05-17T10:00:00Z",
    }


class TestProjectStorageHygiene:
    def test_empty_inputs_returns_empty_summary(self):
        hygiene = ProjectStorageHygiene()
        summary = hygiene.build_project_summary([], [])
        assert summary.total_snapshots == 0
        assert summary.total_llm_events == 0
        assert summary.project_profiles == []

    def test_single_project_profile_built(self):
        hygiene = ProjectStorageHygiene()
        summary = hygiene.build_project_summary(
            [_snap_row("proj-a", 50)],
            [_event_row("proj-a", 1000)],
        )
        assert len(summary.project_profiles) == 1
        profile = summary.project_profiles[0]
        assert profile.project_id == "proj-a"
        assert profile.snapshot_count == 50
        assert profile.llm_event_count == 1000

    def test_snapshot_share_is_1_for_single_project(self):
        hygiene = ProjectStorageHygiene()
        summary = hygiene.build_project_summary(
            [_snap_row("proj-a", 100)],
            [_event_row("proj-a", 500)],
        )
        assert abs(summary.project_profiles[0].snapshot_share - 1.0) < 0.001

    def test_multiple_projects_share_computed(self):
        hygiene = ProjectStorageHygiene()
        summary = hygiene.build_project_summary(
            [_snap_row("proj-a", 70), _snap_row("proj-b", 30)],
            [_event_row("proj-a", 700), _event_row("proj-b", 300)],
        )
        proj_a = next(p for p in summary.project_profiles if p.project_id == "proj-a")
        proj_b = next(p for p in summary.project_profiles if p.project_id == "proj-b")
        assert abs(proj_a.snapshot_share - 0.70) < 0.01
        assert abs(proj_b.snapshot_share - 0.30) < 0.01

    def test_runaway_project_detected(self):
        hygiene = ProjectStorageHygiene()
        summary = hygiene.build_project_summary(
            [_snap_row("dominant", 95), _snap_row("other", 5)],
            [_event_row("dominant", 950), _event_row("other", 50)],
        )
        assert "dominant" in summary.runaway_projects

    def test_no_runaway_when_balanced(self):
        hygiene = ProjectStorageHygiene()
        summary = hygiene.build_project_summary(
            [_snap_row("proj-a", 50), _snap_row("proj-b", 50)],
            [_event_row("proj-a", 500), _event_row("proj-b", 500)],
        )
        assert summary.runaway_projects == []

    def test_event_only_project_included(self):
        hygiene = ProjectStorageHygiene()
        summary = hygiene.build_project_summary(
            [],  # no snapshots
            [_event_row("event-only", 100)],
        )
        assert any(p.project_id == "event-only" for p in summary.project_profiles)

    def test_to_dict_serializable(self):
        hygiene = ProjectStorageHygiene()
        summary = hygiene.build_project_summary(
            [_snap_row("proj-a", 50)],
            [_event_row("proj-a", 100)],
        )
        d = summary.to_dict()
        assert "total_snapshots" in d
        assert "project_profiles" in d
        assert "runaway_projects" in d


class TestProjectStorageObservations:
    def test_no_obs_for_balanced(self):
        obs = _project_storage_observations("proj-a", snap_share=0.30, ev_share=0.30)
        assert obs == []

    def test_high_snapshot_share_generates_obs(self):
        obs = _project_storage_observations("proj-a", snap_share=0.80, ev_share=0.10)
        assert any("snapshot" in o.lower() for o in obs)

    def test_high_event_share_generates_obs(self):
        obs = _project_storage_observations("proj-a", snap_share=0.10, ev_share=0.80)
        assert any("event" in o.lower() for o in obs)


class TestConcentrationObservations:
    def test_no_profiles_returns_note(self):
        obs = _concentration_observations([], 0, 0)
        assert any("no" in o.lower() for o in obs)

    def test_balanced_profiles_returns_ok(self):
        profiles = [
            ProjectStorageProfile(
                project_id="a", snapshot_count=50, llm_event_count=100,
                total_tokens=1000, estimated_cost=0.01, latest_snapshot_at=None,
                latest_event_at=None, snapshot_share=0.50, event_share=0.50,
            ),
            ProjectStorageProfile(
                project_id="b", snapshot_count=50, llm_event_count=100,
                total_tokens=1000, estimated_cost=0.01, latest_snapshot_at=None,
                latest_event_at=None, snapshot_share=0.50, event_share=0.50,
            ),
        ]
        obs = _concentration_observations(profiles, 100, 200)
        assert any("balanced" in o.lower() for o in obs)
