from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_health_returns_200() -> None:
    response = client.get("/health")
    assert response.status_code == 200


def test_health_status_is_ok() -> None:
    assert client.get("/health").json()["status"] == "ok"


def test_health_message() -> None:
    assert client.get("/health").json()["message"] == "LeakTrace running"


def test_root_returns_200() -> None:
    response = client.get("/")
    assert response.status_code == 200


def test_root_identifies_application() -> None:
    assert client.get("/").json()["application"] == "LeakTrace"


def test_root_status_and_version() -> None:
    data = client.get("/").json()
    assert data["status"] == "running"
    assert data["version"] == "0.1.0"
