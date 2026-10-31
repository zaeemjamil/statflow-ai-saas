"""
Application entrypoint. Run locally with:

    uvicorn app.main:app --reload

`create_app()` is a factory (rather than a bare module-level `app`) so
tests can construct fresh instances with different settings if a future
phase needs that — see tests/conftest.py.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.upload_limit import UploadSizeLimitMiddleware
from app.services.file_service import UploadLimits


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version="0.1.0",
        # Hide interactive docs in production; harmless in dev/staging.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
    )

    # Added before CORS so that CORS remains the outermost layer (the last
    # middleware added wraps all earlier ones) and an early 413 still carries
    # its CORS headers.
    app.add_middleware(
        UploadSizeLimitMiddleware,
        api_prefix=settings.API_V1_PREFIX,
        max_body_bytes=lambda: UploadLimits.from_settings(get_settings()).hard_ceiling_bytes,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.FRONTEND_URL],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        """Unversioned root check for load balancers/orchestrators that
        expect one without knowing about API versioning."""
        return {"service": "zaimex-api", "status": "ok"}

    return app


app = create_app()
