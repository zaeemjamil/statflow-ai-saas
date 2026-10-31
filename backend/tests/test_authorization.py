"""Tests for the Phase 6+ ownership-check pattern (Phase 5 §9,
"Authorization Foundation"). No project/file/report models exist to
check ownership *of* yet, so these test the helper's logic directly
against plain stand-in objects - exactly the structural-typing point of
using a Protocol rather than a concrete base class."""

import uuid
from dataclasses import dataclass

import pytest

from app.core.authorization import ensure_owner
from app.core.exceptions import NotFoundException
from app.models import User


@dataclass
class _FakeResource:
    """Anything with a `user_id` satisfies `HasUserId` structurally -
    this stands in for Project/Subscription/UsageRecord, or a `.project`
    accessed off File/Analysis/Report, without needing a real one."""

    user_id: uuid.UUID


def test_owner_passes_the_check() -> None:
    owner = User(email="owner@example.com", password_hash="x")
    resource = _FakeResource(user_id=uuid.uuid4())
    owner.id = resource.user_id  # simulate a matching persisted id

    ensure_owner(resource, owner)  # does not raise


def test_non_owner_gets_not_found_not_forbidden() -> None:
    resource = _FakeResource(user_id=uuid.uuid4())
    other_user = User(email="other@example.com", password_hash="x")
    other_user.id = uuid.uuid4()  # deliberately different from resource.user_id

    with pytest.raises(NotFoundException) as exc_info:
        ensure_owner(resource, other_user)

    # Specifically 404-shaped, not 403 - see app/core/authorization.py's
    # docstring for why that distinction is the point of this helper.
    assert exc_info.value.status_code == 404
    assert exc_info.value.error_code == "not_found"
