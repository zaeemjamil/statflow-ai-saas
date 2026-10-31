"""
Behavior tests against a real (SQLite) database connection — constraint
enforcement, relationship navigation, cascades, and default values.
Structural/metadata-only checks live in test_models.py.
"""

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Analysis,
    File,
    FileType,
    Project,
    ProjectStatus,
    Report,
    Statistic,
    Subscription,
    UsageRecord,
    User,
    Visualization,
)


def _make_user(session: Session, email: str = "user@example.com") -> User:
    user = User(email=email, password_hash="hashed")
    session.add(user)
    session.commit()
    return user


def _make_project(session: Session, user: User, name: str = "Q3 Sales") -> Project:
    project = Project(user_id=user.id, name=name)
    session.add(project)
    session.commit()
    return project


def _make_file(session: Session, project: Project) -> File:
    file = File(
        project_id=project.id,
        storage_key="uploads/abc.csv",
        original_filename="abc.csv",
        file_type=FileType.CSV,
        size_bytes=1024,
    )
    session.add(file)
    session.commit()
    return file


def _make_analysis(session: Session, project: Project, file: File) -> Analysis:
    analysis = Analysis(project_id=project.id, file_id=file.id)
    session.add(analysis)
    session.commit()
    return analysis


# --- unique email -----------------------------------------------------


def test_duplicate_email_is_rejected(db_session: Session) -> None:
    _make_user(db_session, email="dup@example.com")
    db_session.add(User(email="dup@example.com", password_hash="x"))
    with pytest.raises(IntegrityError):
        db_session.commit()


# --- foreign key enforcement -------------------------------------------


def test_project_with_nonexistent_user_is_rejected(db_session: Session) -> None:
    db_session.add(Project(user_id=uuid.uuid4(), name="Orphan"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_file_with_nonexistent_project_is_rejected(db_session: Session) -> None:
    db_session.add(
        File(
            project_id=uuid.uuid4(),
            storage_key="k",
            original_filename="f.csv",
            file_type=FileType.CSV,
            size_bytes=1,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


# --- relationships ------------------------------------------------------


def test_project_to_user_relationship(db_session: Session) -> None:
    user = _make_user(db_session)
    project = _make_project(db_session, user)

    assert project.user.id == user.id
    assert project.user.email == user.email
    assert project in user.projects


def test_file_to_project_relationship(db_session: Session) -> None:
    user = _make_user(db_session)
    project = _make_project(db_session, user)
    file = _make_file(db_session, project)

    assert file.project.id == project.id
    assert file in project.files


def test_analysis_to_project_and_file_relationship(db_session: Session) -> None:
    user = _make_user(db_session)
    project = _make_project(db_session, user)
    file = _make_file(db_session, project)
    analysis = _make_analysis(db_session, project, file)

    assert analysis.project.id == project.id
    assert analysis.file.id == file.id
    assert analysis in project.analyses
    assert analysis in file.analyses


def test_report_to_project_relationship(db_session: Session) -> None:
    user = _make_user(db_session)
    project = _make_project(db_session, user)
    file = _make_file(db_session, project)
    analysis = _make_analysis(db_session, project, file)

    report = Report(project_id=project.id, analysis_id=analysis.id, storage_key="reports/r.pdf")
    db_session.add(report)
    db_session.commit()

    assert report.project.id == project.id
    assert report.analysis.id == analysis.id
    assert report in project.reports


def test_statistic_and_visualization_belong_to_analysis(db_session: Session) -> None:
    user = _make_user(db_session)
    project = _make_project(db_session, user)
    file = _make_file(db_session, project)
    analysis = _make_analysis(db_session, project, file)

    stat = Statistic(analysis_id=analysis.id, column_name="Revenue", metric="mean", value=1234.5)
    viz = Visualization(analysis_id=analysis.id, chart_type="histogram", config={"x": "Revenue"})
    db_session.add_all([stat, viz])
    db_session.commit()

    assert stat in analysis.statistics
    assert viz in analysis.visualizations


def test_subscription_and_usage_belong_to_user(db_session: Session) -> None:
    user = _make_user(db_session)
    sub = Subscription(user_id=user.id)
    usage = UsageRecord(user_id=user.id, metric="analyses_run", period_start=date(2026, 9, 1))
    db_session.add_all([sub, usage])
    db_session.commit()

    assert user.subscription is not None
    assert user.subscription.id == sub.id
    assert usage in user.usage_records


# --- cascade deletes ------------------------------------------------------


def test_deleting_a_project_cascades_to_its_children(db_session: Session) -> None:
    user = _make_user(db_session)
    project = _make_project(db_session, user)
    file = _make_file(db_session, project)
    analysis = _make_analysis(db_session, project, file)
    db_session.add(Report(project_id=project.id, analysis_id=analysis.id, storage_key="r.pdf"))
    db_session.commit()

    db_session.delete(project)
    db_session.commit()

    assert db_session.get(File, file.id) is None
    assert db_session.get(Analysis, analysis.id) is None
    assert db_session.query(Report).count() == 0


def test_deleting_a_user_cascades_to_their_projects(db_session: Session) -> None:
    user = _make_user(db_session)
    project = _make_project(db_session, user)

    db_session.delete(user)
    db_session.commit()

    assert db_session.get(Project, project.id) is None


# --- timestamps / defaults --------------------------------------------


def test_created_at_and_updated_at_are_populated_on_insert(db_session: Session) -> None:
    user = _make_user(db_session)
    db_session.refresh(user)

    assert isinstance(user.created_at, datetime)
    assert isinstance(user.updated_at, datetime)

    # SQLite has no real timestamptz type, so a DateTime(timezone=True)
    # server_default round-trips as a naive datetime there even though
    # the same column comes back tz-aware on real Postgres — a SQLite
    # testing artifact, not something the schema needs to accommodate.
    created_at = user.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)

    # Just-created timestamps should be recent, not some default like
    # the epoch — a loose sanity bound rather than an exact match.
    assert (datetime.now(UTC) - created_at).total_seconds() < 60


def test_project_status_defaults_to_created(db_session: Session) -> None:
    user = _make_user(db_session)
    project = _make_project(db_session, user)
    db_session.refresh(project)

    assert project.status == ProjectStatus.CREATED


def test_usage_count_defaults_to_zero(db_session: Session) -> None:
    user = _make_user(db_session)
    record = UsageRecord(user_id=user.id, metric="reports_generated", period_start=date(2026, 9, 1))
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)

    assert record.count == 0
