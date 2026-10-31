"""
Project business logic. `get_owned_project` is the one place every
project-scoped endpoint (projects, uploads, analysis) goes through to
turn a project_id into a real, owned Project. Ownership is enforced in
the SQL WHERE clause, so a foreign project is indistinguishable from a
missing one. (`core.authorization.ensure_owner` remains for resources
already loaded through a parent that was ownership-scoped.)
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundException
from app.models import Project, User
from app.services.storage_service import StorageService

logger = logging.getLogger("zaimex.projects")


def create_project(db: Session, *, user: User, name: str) -> Project:
    project = Project(user_id=user.id, name=name)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def list_projects(db: Session, *, user: User) -> list[Project]:
    stmt = select(Project).where(Project.user_id == user.id).order_by(Project.created_at.desc())
    return list(db.scalars(stmt))


def get_owned_project(db: Session, *, project_id: uuid.UUID, user: User) -> Project:
    """Ownership is part of the query, not a check applied afterwards.

    Loading the row first and then comparing owners meant a project that
    existed but belonged to someone else took a different code path - and
    returned a different message - than one that didn't exist, which let
    a caller probe for valid project IDs. (Caught in Phase 8A: status
    codes matched, bodies didn't.) With the filter in SQL, another
    user's project is simply not found, by exactly the same route."""
    project = db.scalar(select(Project).where(Project.id == project_id, Project.user_id == user.id))
    if project is None:
        raise NotFoundException("The requested project was not found.")
    return project


def update_project(db: Session, *, project: Project, name: str) -> Project:
    project.name = name
    db.commit()
    db.refresh(project)
    return project


def delete_project(db: Session, *, project: Project, storage: StorageService) -> None:
    """DB deletion (cascading to files/analyses/reports, Phase 4) is the
    source of truth and always runs first — a project the user asked to
    delete must actually disappear from the database even if storage
    cleanup below has a problem. Storage keys are captured before the
    delete, since the File rows won't exist to read them from
    afterward. Deleting the underlying bytes is best-effort: a failure
    here (the file already gone, a permissions/IO hiccup) is logged, not
    raised, because failing the whole delete request over an orphaned
    file being harder to clean up later is the wrong trade-off — an
    orphaned file wastes disk space; a project that won't delete is a
    much worse user-facing failure.
    """
    storage_keys = [f.storage_key for f in project.files] + [r.storage_key for r in project.reports]

    db.delete(project)
    db.commit()

    for key in storage_keys:
        try:
            storage.delete_file(storage_key=key)
        except Exception:
            logger.warning("Failed to delete storage object %r after project deletion", key)
