"""Tests for RuntimeHealthIntelligence."""

from cognition.runtime_health import RuntimeHealthIntelligence


def _base_state(**overrides) -> dict:
    state = {
        "cpu_percent": 20.0,
        "cpu_count": 2,
        "memory_percent": 40.0,
        "memory_used_gb": 1.6,
        "memory_total_gb": 4.0,
        "swap_percent": 0.0,
        "disk_percent": 50.0,
        "disk_free_gb": 20.0,
        "load_avg_1m": 0.5,
        "load_avg_5m": 0.4,
        "load_avg_15m": 0.3,
        "uptime_hours": 100.0,
        "process_count": 80,
        "zombie_count": 0,
        "failed_services": [],
        "docker_restart_stats": [],
    }
    state.update(overrides)
    return state


class TestRuntimeHealthIntelligence:
    def test_healthy_system(self):
        state = _base_state()
        report = RuntimeHealthIntelligence().assess(state)
        assert report.overall_status == "healthy"
        assert report.health_score > 0.8
        assert not report.instability_signals
        assert not report.resource_pressure

    def test_high_cpu_produces_pressure(self):
        state = _base_state(cpu_percent=90.0)
        report = RuntimeHealthIntelligence().assess(state)
        assert report.overall_status in ("stressed", "critical")
        assert any("CPU" in p for p in report.resource_pressure)

    def test_critical_cpu(self):
        state = _base_state(cpu_percent=97.0)
        report = RuntimeHealthIntelligence().assess(state)
        cpu_ind = next(i for i in report.indicators if i.name == "CPU")
        assert cpu_ind.status == "critical"

    def test_high_memory_produces_pressure(self):
        state = _base_state(memory_percent=90.0)
        report = RuntimeHealthIntelligence().assess(state)
        assert any("Memory" in p for p in report.resource_pressure)

    def test_swap_usage_shows_indicator(self):
        state = _base_state(swap_percent=30.0)
        report = RuntimeHealthIntelligence().assess(state)
        swap_ind = next((i for i in report.indicators if i.name == "Swap"), None)
        assert swap_ind is not None
        assert swap_ind.status != "ok"

    def test_high_disk_produces_pressure(self):
        state = _base_state(disk_percent=88.0)
        report = RuntimeHealthIntelligence().assess(state)
        assert any("Disk" in p for p in report.resource_pressure)

    def test_failed_services_signals_instability(self):
        state = _base_state(failed_services=["nginx.service", "redis.service"])
        report = RuntimeHealthIntelligence().assess(state)
        assert report.failed_services == ["nginx.service", "redis.service"]
        assert any("nginx" in sig for sig in report.instability_signals)

    def test_docker_restarts_detected(self):
        state = _base_state(docker_restart_stats=[
            {"name": "myapp", "status": "Up", "restart_count": 5},
            {"name": "worker", "status": "Up", "restart_count": 1},
        ])
        report = RuntimeHealthIntelligence().assess(state)
        assert report.has_docker_restarts is True
        assert len(report.docker_restart_details) == 1  # only restart_count >= 3
        assert "myapp" in report.docker_restart_details[0]

    def test_zombie_processes_signal(self):
        state = _base_state(zombie_count=6)
        report = RuntimeHealthIntelligence().assess(state)
        assert any("zombie" in sig.lower() for sig in report.instability_signals)

    def test_high_load_detected(self):
        state = _base_state(cpu_count=2, load_avg_1m=5.0)  # > 2× cores
        report = RuntimeHealthIntelligence().assess(state)
        load_ind = next((i for i in report.indicators if "Load" in i.name), None)
        assert load_ind is not None
        assert load_ind.status == "critical"

    def test_unavailable_state_returns_unknown(self):
        report = RuntimeHealthIntelligence().assess({})
        assert report.overall_status == "unknown"
        assert report.health_score == 0.5

    def test_error_state_returns_unknown(self):
        report = RuntimeHealthIntelligence().assess({"error": "scanner failed"})
        assert report.overall_status == "unknown"

    def test_health_score_range(self):
        state = _base_state()
        report = RuntimeHealthIntelligence().assess(state)
        assert 0.0 <= report.health_score <= 1.0

    def test_to_dict_structure(self):
        report = RuntimeHealthIntelligence().assess(_base_state())
        d = report.to_dict()
        assert "overall_status" in d
        assert "health_score" in d
        assert "indicators" in d
        assert "instability_signals" in d
        assert "resource_pressure" in d
        assert "failed_services" in d
        assert "has_docker_restarts" in d
