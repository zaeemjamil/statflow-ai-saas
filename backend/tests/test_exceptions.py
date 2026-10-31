"""
No real business endpoint exists yet to trigger these naturally, so each
test mounts a throwaway route on a fresh FastAPI app with the same
`register_exception_handlers` production code wires up — this tests the
actual reusable infrastructure, not a stand-in for it.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.exceptions import NotFoundException, register_exception_handlers


def _app_with_route_that_raises(exc: Exception) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise exc

    return app


def _app_with_required_query_param() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/needs-a-value")
    def needs_a_value(value: int) -> dict[str, int]:
        return {"value": value}

    return app


def test_app_exception_returns_the_common_error_shape() -> None:
    app = _app_with_route_that_raises(NotFoundException("Project not found"))
    response = TestClient(app).get("/boom")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Project not found"}}


def test_request_validation_error_uses_the_common_error_shape() -> None:
    # A real malformed request (missing required query param), not a
    # deliberately-raised exception — this is FastAPI's own automatic
    # RequestValidationError, collapsed into the same ErrorResponse
    # shape as every other error rather than FastAPI's default
    # field-path-heavy format.
    response = TestClient(_app_with_required_query_param()).get("/needs-a-value")

    assert response.status_code == 422
    body = response.json()
    assert body.keys() == {"error"}
    assert body["error"]["code"] == "validation_error"
    assert "value" in body["error"]["message"]  # names the missing field


def test_request_validation_error_accepts_a_valid_request() -> None:
    response = TestClient(_app_with_required_query_param()).get("/needs-a-value?value=5")
    assert response.status_code == 200
    assert response.json() == {"value": 5}


def test_unhandled_exception_returns_500_not_a_raw_traceback() -> None:
    app = _app_with_route_that_raises(ValueError("boom"))
    # raise_server_exceptions=False: TestClient's default re-raises the
    # original exception in the test process even when a registered
    # handler produced a valid response (confirmed with a standalone
    # repro against this FastAPI/Starlette version) — real clients never
    # see that re-raise, only TestClient's default test ergonomics do.
    response = TestClient(app, raise_server_exceptions=False).get("/boom")

    assert response.status_code == 500
    assert "error" in response.json()


def test_unhandled_exception_hides_details_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.setenv("JWT_SECRET", "a" * 32)
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    monkeypatch.setenv("COOKIE_SECURE", "true")  # a valid production config requires HTTPS
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")
    get_settings.cache_clear()

    app = _app_with_route_that_raises(ValueError("super secret internal detail"))
    response = TestClient(app, raise_server_exceptions=False).get("/boom")

    assert response.status_code == 500
    assert "super secret internal detail" not in response.json()["error"]["message"]
