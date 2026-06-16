from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_root_returns_ok() -> None:
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "operational"
    assert "version" in data


def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "uptime_seconds" in data
    assert "version" in data


def test_health_uptime_is_positive() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["uptime_seconds"] >= 0
