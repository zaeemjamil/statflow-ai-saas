"""
Runs the real initial migration end-to-end against a temp SQLite file —
not mocked, not just "the file exists". Confirms both that autogenerate
produced a migration Alembic can actually apply, and that it's
reversible.
"""

import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command

BACKEND_ROOT = Path(__file__).resolve().parent.parent

EXPECTED_TABLES = {
    "users",
    "projects",
    "files",
    "analyses",
    "statistics",
    "visualizations",
    "reports",
    "subscriptions",
    "usage",
    "password_reset_tokens",
    "alembic_version",
}


@pytest.fixture()
def alembic_config() -> Iterator[Config]:
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "migration_test.db"
        cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
        yield cfg


def test_migration_upgrades_to_head_and_creates_every_table(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")

    db_url = alembic_config.get_main_option("sqlalchemy.url")
    assert db_url is not None
    engine = create_engine(db_url)
    tables = set(inspect(engine).get_table_names())

    assert tables == EXPECTED_TABLES
    engine.dispose()


def test_migration_downgrade_removes_every_table(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")

    db_url = alembic_config.get_main_option("sqlalchemy.url")
    assert db_url is not None
    engine = create_engine(db_url)
    tables = set(inspect(engine).get_table_names())

    # alembic_version itself survives a downgrade to "base" (it just
    # records that no revision is applied) - every domain table doesn't.
    assert tables & EXPECTED_TABLES == ({"alembic_version"} & tables)
    engine.dispose()


def test_migration_is_re_appliable_after_downgrade(alembic_config: Config) -> None:
    # A migration that only works once (e.g. a non-idempotent index name
    # collision) is a real, common Alembic footgun - round-tripping
    # catches it.
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")

    db_url = alembic_config.get_main_option("sqlalchemy.url")
    assert db_url is not None
    engine = create_engine(db_url)
    tables = set(inspect(engine).get_table_names())

    assert tables == EXPECTED_TABLES
    engine.dispose()
