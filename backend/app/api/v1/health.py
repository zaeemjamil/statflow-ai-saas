from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas.common import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Liveness check. Deliberately doesn't touch the database yet — a
    DB-readiness check can be added once Phase 4 models exist, so this
    endpoint doesn't report unhealthy for a reason unrelated to whether
    the API process itself is up."""
    settings = get_settings()
    return HealthResponse(status="ok", environment=settings.ENVIRONMENT, version="0.1.0")
