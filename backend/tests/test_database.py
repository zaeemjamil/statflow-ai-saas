"""
These tests confirm the SQLAlchemy/psycopg2 plumbing is wired correctly
without needing a reachable Postgres server — SQLAlchemy resolves the
dialect+driver at engine-construction time, and creating a Session
doesn't open a connection until a query actually runs. Real connectivity
against a live database is Phase 4's job, once there's an actual
database to point at.
"""

import pytest
from sqlalchemy.orm import DeclarativeBase, Session

from app.core.database import Base, engine, get_db


def test_base_is_a_declarative_base() -> None:
    assert issubclass(Base, DeclarativeBase)


def test_engine_resolves_the_postgres_driver() -> None:
    assert engine.url.get_backend_name() == "postgresql"


def test_get_db_yields_a_session_and_closes_cleanly() -> None:
    gen = get_db()
    session = next(gen)
    assert isinstance(session, Session)
    with pytest.raises(StopIteration):
        next(gen)  # exhausts the generator, running `finally: db.close()`
