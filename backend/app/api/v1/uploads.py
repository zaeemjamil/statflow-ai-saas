from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_storage
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.exceptions import NotFoundException
from app.models import File, FileType, User
from app.schemas.upload import DatasetProfile, FileInfo, UploadResponse
from app.services import file_service, project_service
from app.services.file_service import UploadLimits
from app.services.storage_service import StorageService

router = APIRouter(prefix="/projects", tags=["uploads"])


def _read_bounded(file: UploadFile, max_bytes: int, file_type: FileType) -> bytes:
    """Reads in chunks, rejecting as soon as the limit for this file type is
    exceeded, rather than buffering an arbitrarily large upload fully into
    memory before checking its size. Uses the underlying
    SpooledTemporaryFile's sync `.read()` (via `file.file`) rather than
    UploadFile's own async `.read()` - this handler is a plain `def`,
    consistent with every other route in this codebase (sync SQLAlchemy
    throughout; FastAPI runs sync `def` handlers in a threadpool
    automatically), so the read needs to be sync too. Verified this
    doesn't require the async wrapper by testing it directly against a
    real UploadFile with a deliberately tiny chunk size.

    Note this runs after the framework has already received the multipart
    body (FastAPI parses it before calling the handler), so it bounds this
    process's memory, not bandwidth or spool-file disk use; that is what the
    Content-Length middleware (app/core/upload_limit.py) and any reverse
    proxy limit are for."""
    chunks: list[bytes] = []
    total = 0
    chunk_size = 1024 * 1024
    while True:
        chunk = file.file.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise file_service.file_too_large_error(file_type, max_bytes)
        chunks.append(chunk)
    return b"".join(chunks)


@router.post(
    "/{project_id}/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED
)
def upload_file(
    project_id: uuid.UUID,
    file: UploadFile,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    storage: StorageService = Depends(get_storage),
) -> UploadResponse:
    # Ownership checked before touching the upload stream at all - an
    # upload to a project you don't own gets 404, not a wasted parse.
    project = project_service.get_owned_project(db, project_id=project_id, user=current_user)

    # Everything that can be decided without the body is decided before
    # reading it: a second upload, or an unsupported extension, must not cost
    # a 25 MB read. (Type is by extension only; parseability is checked later.)
    file_service.ensure_project_has_no_file(db, project)
    filename = file.filename or "upload"
    file_type = file_service.detect_file_type(filename)

    limits = UploadLimits.from_settings(settings)
    content = _read_bounded(file, limits.max_bytes_for(file_type), file_type)

    file_row, profile = file_service.process_upload(
        db,
        project=project,
        filename=filename,
        content=content,
        storage=storage,
        limits=limits,
    )

    return UploadResponse(
        file=FileInfo.model_validate(file_row),
        profile=DatasetProfile.model_validate(profile),
    )


@router.get("/{project_id}/profile", response_model=DatasetProfile)
def get_profile(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DatasetProfile:
    """Re-fetches the profiling result stored at upload time (File.profile)
    rather than re-reading and re-parsing the file from storage - the
    Phase 2 Dataset Profiling screen can be revisited without a network
    round trip to object storage on every view."""
    project = project_service.get_owned_project(db, project_id=project_id, user=current_user)
    file_row = db.scalar(select(File).where(File.project_id == project.id))
    if file_row is None or file_row.profile is None:
        raise NotFoundException("No uploaded file/profile was found for this project.")
    return DatasetProfile.model_validate(file_row.profile)


@router.get("/{project_id}/file", response_model=FileInfo)
def get_file_info(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileInfo:
    """Metadata of the project's uploaded file (V1: at most one), so the
    frontend can show the filename/size after a reload - the upload
    response is the only other place this is exposed."""
    project = project_service.get_owned_project(db, project_id=project_id, user=current_user)
    file_row = db.scalar(select(File).where(File.project_id == project.id))
    if file_row is None:
        raise NotFoundException("No uploaded file was found for this project.")
    return FileInfo.model_validate(file_row)
