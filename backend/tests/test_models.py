"""
Structural tests — inspect the SQLAlchemy metadata/mapper configuration
directly, no database connection needed. DB-behavior tests (constraint
enforcement, cascades, timestamps) live in test_models_db.py.
"""

from sqlalchemy.orm import configure_mappers

import app.models as models
from app.core.database import Base

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
}


def test_all_ten_models_import_successfully() -> None:
    expected_names = [
        "User",
        "Project",
        "File",
        "Analysis",
        "Statistic",
        "Visualization",
        "Report",
        "Subscription",
        "UsageRecord",
        "PasswordResetToken",
    ]
    for name in expected_names:
        assert hasattr(models, name), f"app.models is missing {name}"


def test_every_relationship_resolves() -> None:
    # Fails loudly if any relationship()'s string reference (e.g.
    # "Project") doesn't match a real mapped class — the most common way
    # a multi-file model set silently breaks.
    configure_mappers()


def test_table_metadata_has_exactly_the_required_entities() -> None:
    assert set(Base.metadata.tables.keys()) == EXPECTED_TABLES


def test_every_table_has_a_single_uuid_primary_key() -> None:
    for name, table in Base.metadata.tables.items():
        pk_columns = list(table.primary_key.columns)
        assert len(pk_columns) == 1, f"{name} should have exactly one PK column"
        assert pk_columns[0].name == "id", f"{name}'s PK should be named 'id'"


def test_foreign_keys_point_at_the_right_parent_tables() -> None:
    expected: dict[str, set[tuple[str, str]]] = {
        "projects": {("user_id", "users")},
        "files": {("project_id", "projects")},
        "analyses": {("project_id", "projects"), ("file_id", "files")},
        "statistics": {("analysis_id", "analyses")},
        "visualizations": {("analysis_id", "analyses")},
        "reports": {("project_id", "projects"), ("analysis_id", "analyses")},
        "subscriptions": {("user_id", "users")},
        "usage": {("user_id", "users")},
        "password_reset_tokens": {("user_id", "users")},
    }
    for table_name, expected_fks in expected.items():
        table = Base.metadata.tables[table_name]
        actual_fks = {(fk.parent.name, fk.column.table.name) for fk in table.foreign_keys}
        assert actual_fks == expected_fks, (
            f"{table_name} foreign keys: {actual_fks} != {expected_fks}"
        )


def test_every_foreign_key_cascades_on_delete() -> None:
    for name, table in Base.metadata.tables.items():
        for fk in table.foreign_keys:
            assert fk.ondelete == "CASCADE", f"{name}.{fk.parent.name} is not ON DELETE CASCADE"


def test_every_foreign_key_column_is_indexed() -> None:
    # This is what makes `project.user_id == current_user.id`-style
    # ownership checks fast rather than a sequential scan. A column that
    # is `unique=True` (e.g. subscriptions.user_id) already gets a
    # unique index from the constraint itself — adding a second,
    # separate explicit index alongside it would just be a redundant
    # index covering the same single column, so that case counts too.
    for name, table in Base.metadata.tables.items():
        indexed_columns = {col.name for idx in table.indexes for col in idx.columns}
        for fk in table.foreign_keys:
            column = fk.parent
            is_indexed = column.name in indexed_columns or column.unique
            assert is_indexed, f"{name}.{column.name} is a foreign key but has no index"


def test_users_email_is_unique() -> None:
    email_column = Base.metadata.tables["users"].columns["email"]
    assert email_column.unique or any(
        "email" in idx.columns and idx.unique for idx in Base.metadata.tables["users"].indexes
    )


def test_subscriptions_user_id_is_unique() -> None:
    user_id_column = Base.metadata.tables["subscriptions"].columns["user_id"]
    assert user_id_column.unique


def test_append_only_tables_have_no_updated_at() -> None:
    # statistics/visualizations/reports are immutable once written
    # (Phase 4 design overview §"timestamps where appropriate").
    # password_reset_tokens *does* get one field mutated (used_at, when
    # consumed) but that's already a specific, more informative
    # timestamp than a generic updated_at would be - same reasoning as
    # reports.generated_at not needing a redundant updated_at either.
    for name in ("statistics", "visualizations", "reports", "password_reset_tokens"):
        assert "updated_at" not in Base.metadata.tables[name].columns


def test_mutable_tables_have_created_and_updated_at() -> None:
    for name in ("users", "projects", "files", "analyses", "subscriptions", "usage"):
        columns = Base.metadata.tables[name].columns
        assert "created_at" in columns
        assert "updated_at" in columns
