"""
Database session foundation.

This sets up the SQLAlchemy engine, session factory, and declarative
base that every Phase 4 model will use — but defines no models itself.
`get_db` is the FastAPI dependency route handlers will take a `Session`
from, starting in Phase 4.

Sync SQLAlchemy (not the async engine) is used deliberately: FastAPI runs
sync `def` path operations in a threadpool automatically, which is a
simpler, well-trodden pattern than async SQLAlchemy + greenlet for a
project this size, and it keeps pandas-heavy analytics code (also sync)
from needing a separate execution model later.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """Shared declarative base — Phase 4 models subclass this."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a request-scoped session, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
