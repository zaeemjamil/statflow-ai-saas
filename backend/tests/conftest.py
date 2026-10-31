"""
Test env vars must be set before `app.main` is first imported anywhere,
since `create_app()` reads settings at import time. Setting them at
conftest module level (rather than in a fixture) guarantees that.
"""

import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://test:test@localhost:5432/zaimex_test")
os.environ.setdefault("FRONTEND_URL", "http://localhost:3000")
# TestClient talks to the app over plain http://testserver, not real
# HTTPS - a Secure-flagged cookie (the correct, safe production default)
# would be silently dropped by the client on every request after the
# one that sets it. This mirrors what real local dev over http also
# needs; it is not a relaxation of the production security default.
os.environ.setdefault("COOKIE_SECURE", "false")

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture(autouse=True)
def _reset_throttles() -> Iterator[None]:
    """Attempt limiters are process-wide; no test may inherit another's failures."""
    from app.core.throttle import login_limiter, reset_limiter

    login_limiter.clear()
    reset_limiter.clear()
    yield
    login_limiter.clear()
    reset_limiter.clear()


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    """`get_settings` is process-cached (lru_cache). Without this, a test
    that changes env vars and fails before its own cleanup line runs
    would leak stale settings into every test after it - clearing the
    cache before and after every test makes that impossible regardless
    of how an individual test fails."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def test_engine() -> Iterator[Engine]:
    """A fresh in-memory SQLite database per test - no real Postgres
    required (Phase 4 requirement). StaticPool keeps the same in-memory
    database alive across the whole test despite SQLAlchemy normally
    opening a new connection (and thus a new blank in-memory DB) per
    checkout. Foreign keys are OFF by default in SQLite, unlike
    Postgres, so they're switched on explicitly per connection - without
    this, FK-violation tests would silently pass for the wrong reason.

    `db_session` and `client` both build on this same fixture so a test
    using both sees one consistent database, not two unrelated ones -
    e.g. "register via a real HTTP request, then inspect the resulting
    row directly" needs the HTTP call and the direct query to hit the
    same data.
    """
    import app.models  # noqa: F401  (registers every table on Base.metadata)
    from app.core.database import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def db_session(test_engine: Engine) -> Iterator[Session]:
    session = sessionmaker(bind=test_engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(test_engine: Engine) -> Iterator[TestClient]:
    """A TestClient whose `get_db` dependency is overridden to use the
    same SQLite database as `test_engine`/`db_session` - without this,
    endpoints that touch the database would fall through to the real
    (Postgres) DATABASE_URL, which is an intentionally-unreachable
    placeholder in tests. `get_storage` is likewise overridden to a
    fresh temp directory per test, rather than every test sharing (and
    leaving files behind in) Settings.LOCAL_STORAGE_PATH."""
    import tempfile

    from app.api.deps import get_storage
    from app.core.database import get_db
    from app.services.storage_service import LocalStorageService

    session_factory = sessionmaker(bind=test_engine)

    def _override_get_db() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db

    with tempfile.TemporaryDirectory() as tmp_storage_dir:
        app.dependency_overrides[get_storage] = lambda: LocalStorageService(tmp_storage_dir)
        try:
            yield TestClient(app)
        finally:
            app.dependency_overrides.clear()
