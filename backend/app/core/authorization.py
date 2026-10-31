"""
Reusable ownership-check pattern for Phase 6+.

Every project-scoped resource reaches its owner through `.project.user_id`,
not a `user_id` column of its own (`files`/`analyses`/`reports` in Phase
4's schema) — so `ensure_owner` takes whatever object actually carries
the `user_id` to check. Callers pass either the resource directly
(`Project`, `Subscription`, `UsageRecord`, which do have their own
`user_id`) or its `.project` for anything nested under one:

    ensure_owner(project, current_user)          # Project itself
    ensure_owner(file.project, current_user)      # File, via its project
    ensure_owner(analysis.project, current_user)  # Analysis, via its project
    ensure_owner(report.project, current_user)    # Report, via its project

Raises NotFoundException, not a 403: a resource that exists but belongs
to someone else must be indistinguishable from one that doesn't exist at
all (see NotFoundException's own docstring in app.core.exceptions) — a
403 would confirm the resource's existence to a caller who isn't
entitled to know that.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from app.core.exceptions import NotFoundException
from app.models import User


class HasUserId(Protocol):
    user_id: uuid.UUID


def ensure_owner(resource: HasUserId, current_user: User) -> None:
    if resource.user_id != current_user.id:
        raise NotFoundException("The requested resource was not found.")
