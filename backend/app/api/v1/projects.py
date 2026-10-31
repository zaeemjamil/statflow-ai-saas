from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_storage
from app.core.database import get_db
from app.models import Project, User
from app.schemas.project import ProjectCreate, ProjectPublic, ProjectUpdate
from app.services import project_service
from app.services.storage_service import StorageService

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectPublic, status_code=status.HTTP_201_CREATED)
def create_project(
    body: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Project:
    return project_service.create_project(db, user=current_user, name=body.name)


@router.get("", response_model=list[ProjectPublic])
def list_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Project]:
    return project_service.list_projects(db, user=current_user)


@router.get("/{project_id}", response_model=ProjectPublic)
def get_project(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Project:
    return project_service.get_owned_project(db, project_id=project_id, user=current_user)


@router.patch("/{project_id}", response_model=ProjectPublic)
def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Project:
    project = project_service.get_owned_project(db, project_id=project_id, user=current_user)
    return project_service.update_project(db, project=project, name=body.name)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage: StorageService = Depends(get_storage),
) -> None:
    project = project_service.get_owned_project(db, project_id=project_id, user=current_user)
    project_service.delete_project(db, project=project, storage=storage)
