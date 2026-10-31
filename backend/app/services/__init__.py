"""
Service layer — structure only in Phase 3, files added as their phase
needs them (file_service.py in Phase 6, analysis_service.py in Phase 7,
ai_service.py in Phase 9, report_service.py in Phase 10).

Convention every service will follow, so this stays consistent as it
fills in: a service is a plain class taking its dependencies (a DB
`Session`, `Settings`) through `__init__`, with one public method per
use case. Routers call services; services call `app.analytics` functions
and models — analytics functions never import FastAPI or touch the
database directly, so they stay unit-testable in isolation.
"""
