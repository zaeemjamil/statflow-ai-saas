from fastapi.testclient import TestClient


def test_root_reports_ok(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"service": "zaimex-api", "status": "ok"}


def test_versioned_health_endpoint(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["environment"] == "test"
    assert body["version"] == "0.1.0"


def test_unmatched_route_is_a_plain_404(client: TestClient) -> None:
    # No route handler runs for a URL that matches nothing, so this hits
    # Starlette's default 404, not our AppException handler — see
    # test_exceptions.py for the custom error-shape coverage.
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
