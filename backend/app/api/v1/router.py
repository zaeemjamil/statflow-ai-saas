"""
Aggregates every /api/v1/* sub-router into one - app/main.py never
needs to change as endpoints are added.
"""

from fastapi import APIRouter

from app.api.v1 import ai, analysis, auth, dashboard, health, projects, reports, uploads

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(uploads.router)
api_router.include_router(analysis.router)
api_router.include_router(ai.router)
api_router.include_router(reports.router)
api_router.include_router(dashboard.router)
