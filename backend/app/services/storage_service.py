"""
Storage abstraction. `StorageService` is the interface every future
provider (local disk now, S3-compatible later) implements, so
`file_service.py` never knows or cares which one is active — matching
the requirement not to hardcode a cloud provider into business logic.

The storage_key namespace is server-owned: callers never pass a client-
supplied path, and `LocalStorageService` treats any key it's given as an
opaque identifier, not a filesystem path to interpret - see
`_safe_local_path`'s docstring for exactly what that guards against.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

from app.core.config import Settings

# Server-generated keys only ever look like "uploads/<uuid>.<ext>" (see
# file_service.generate_storage_key), so anything outside this shape
# reaching the storage layer indicates a bug upstream, not a legitimate
# key - rejecting it here is a second line of defense, not the primary
# one (the primary one is that keys are never derived from client input
# to begin with).
_SAFE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._/-]+$")


class StorageService(Protocol):
    def save_file(self, *, storage_key: str, content: bytes) -> None: ...
    def get_file(self, *, storage_key: str) -> bytes: ...
    def delete_file(self, *, storage_key: str) -> None: ...


class StorageKeyError(Exception):
    """A storage_key failed the safety check before touching the
    filesystem - see _SAFE_KEY_PATTERN."""


def _safe_local_path(base_dir: Path, storage_key: str) -> Path:
    """Resolves storage_key under base_dir, refusing anything that could
    escape it (`..`, an absolute path, a symlink-driven escape). This is
    defense in depth, not the primary control - see module docstring."""
    if not _SAFE_KEY_PATTERN.match(storage_key) or ".." in storage_key.split("/"):
        raise StorageKeyError(f"Refusing unsafe storage key: {storage_key!r}")

    resolved_base = base_dir.resolve()
    candidate = (resolved_base / storage_key).resolve()
    if resolved_base not in candidate.parents and candidate != resolved_base:
        raise StorageKeyError(f"Storage key resolves outside the storage root: {storage_key!r}")
    return candidate


class LocalStorageService:
    """Development/test backend - writes under a configured local
    directory. Not what production uses (see STORAGE_ENDPOINT), but
    behind the same interface so swapping it in is a factory change,
    not a call-site change."""

    def __init__(self, base_dir: str) -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def save_file(self, *, storage_key: str, content: bytes) -> None:
        path = _safe_local_path(self._base_dir, storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def get_file(self, *, storage_key: str) -> bytes:
        path = _safe_local_path(self._base_dir, storage_key)
        return path.read_bytes()

    def delete_file(self, *, storage_key: str) -> None:
        path = _safe_local_path(self._base_dir, storage_key)
        path.unlink(missing_ok=True)


def get_storage_service(settings: Settings) -> StorageService:
    if settings.STORAGE_ENDPOINT is None:
        return LocalStorageService(settings.LOCAL_STORAGE_PATH)
    raise NotImplementedError(
        "STORAGE_ENDPOINT is set but no S3-compatible provider is implemented yet - "
        "add one that satisfies StorageService and wire it in here, rather than "
        "silently falling back to local disk for a provider that was explicitly requested."
    )
