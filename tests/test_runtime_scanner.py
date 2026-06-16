"""Tests for RuntimeScanner."""

from scanners.runtime_scanner import RuntimeScanner


def test_scan_returns_expected_keys():
    scanner = RuntimeScanner()
    result = scanner.run("localhost")
    assert "target" in result
    assert "scanned_at" in result
    assert "failed_services" in result
    assert "docker_restart_stats" in result
    assert isinstance(result["failed_services"], list)
    assert isinstance(result["docker_restart_stats"], list)


def test_scan_returns_cpu_and_memory():
    scanner = RuntimeScanner()
    result = scanner.run("localhost")
    # psutil is available in this environment
    assert result.get("cpu_percent") is not None
    assert result.get("memory_percent") is not None
    assert 0.0 <= result["cpu_percent"] <= 100.0
    assert 0.0 <= result["memory_percent"] <= 100.0


def test_scan_returns_disk():
    scanner = RuntimeScanner()
    result = scanner.run("localhost")
    assert "disk_percent" in result
    assert "disk_free_gb" in result
    if result["disk_percent"] is not None:
        assert 0.0 <= result["disk_percent"] <= 100.0


def test_scan_returns_load():
    scanner = RuntimeScanner()
    result = scanner.run("localhost")
    assert "load_avg_1m" in result
    assert "load_avg_5m" in result
    assert "load_avg_15m" in result
    if result["load_avg_1m"] is not None:
        assert result["load_avg_1m"] >= 0.0


def test_scan_returns_uptime():
    scanner = RuntimeScanner()
    result = scanner.run("localhost")
    assert "uptime_hours" in result
    if result["uptime_hours"] is not None:
        assert result["uptime_hours"] >= 0.0


def test_scan_returns_process_stats():
    scanner = RuntimeScanner()
    result = scanner.run("localhost")
    assert "zombie_count" in result
    assert result["zombie_count"] >= 0


def test_scanner_name():
    assert RuntimeScanner.name == "runtime_scanner"


def test_docker_restart_stats_structure():
    scanner = RuntimeScanner()
    result = scanner.run("localhost")
    for item in result["docker_restart_stats"]:
        assert "name" in item
        assert "status" in item
        assert "restart_count" in item
        assert isinstance(item["restart_count"], int)
