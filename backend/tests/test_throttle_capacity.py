"""Login/reset throttle table-capacity behaviour: a full table must never lose a lockout."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.core import throttle
from app.core.config import get_settings
from app.core.throttle import AttemptLimiter

WINDOW = 900.0
LIMIT = 3


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    return now


def _lock(lim: AttemptLimiter, key: str, *, limit: int = LIMIT, window: float = WINDOW) -> None:
    """Fail ``limit`` times the way the login endpoint does: check, then record."""
    for _ in range(limit):
        assert lim.retry_after(key, limit=limit, window=window) == 0
        lim.record(key, window=window)
    assert lim.retry_after(key, limit=limit, window=window) > 0


def _flood(lim: AttemptLimiter, count: int, prefix: str = "email:flood") -> None:
    for i in range(count):
        key = f"{prefix}{i}"
        lim.retry_after(key, limit=LIMIT, window=WINDOW)
        lim.record(key, window=WINDOW)


def test_filling_the_table_never_removes_an_existing_account_or_ip_lockout(
    clock: list[float],
) -> None:
    lim = AttemptLimiter(max_keys=50)
    _lock(lim, "email:victim@example.com")
    _lock(lim, "ip:203.0.113.9", limit=15)
    before = lim.retry_after("email:victim@example.com", limit=LIMIT, window=WINDOW)

    _flood(lim, 5_000)

    assert len(lim._events) <= 50
    assert lim.retry_after("email:victim@example.com", limit=LIMIT, window=WINDOW) > 0
    assert lim.retry_after("ip:203.0.113.9", limit=15, window=WINDOW) > 0
    # Flooding did not shorten or extend the lock.
    assert lim.retry_after("email:victim@example.com", limit=LIMIT, window=WINDOW) == before


def test_a_full_table_is_never_cleared(clock: list[float]) -> None:
    lim = AttemptLimiter(max_keys=20)
    _flood(lim, 20)
    assert len(lim._events) == 20
    lim.record("email:one-more", window=WINDOW)
    assert 0 < len(lim._events) <= 20
    assert "email:one-more" in lim._events  # the new key was admitted by evicting a few others
    assert len(lim._events) > 1  # not "clear everything"


def test_lockouts_survive_through_the_module_cap_used_in_production(
    clock: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(throttle, "_MAX_KEYS", 30)
    lim = AttemptLimiter()  # reads the module cap, like login_limiter does
    _lock(lim, "email:victim@example.com")
    _flood(lim, 1_000)
    assert len(lim._events) <= 30
    assert lim.retry_after("email:victim@example.com", limit=LIMIT, window=WINDOW) > 0


def test_when_every_key_is_an_active_lockout_new_keys_are_not_tracked(
    clock: list[float],
) -> None:
    lim = AttemptLimiter(max_keys=5)
    for i in range(5):
        _lock(lim, f"email:locked{i}")
    lim.record("email:newcomer", window=WINDOW)
    assert lim.untracked_records == 1
    assert "email:newcomer" not in lim._events
    assert len(lim._events) == 5  # bounded
    for i in range(5):
        assert lim.retry_after(f"email:locked{i}", limit=LIMIT, window=WINDOW) > 0


def test_expired_lockouts_free_their_slots(clock: list[float]) -> None:
    lim = AttemptLimiter(max_keys=5)
    for i in range(5):
        _lock(lim, f"email:locked{i}")
    clock[0] += WINDOW + 1
    lim.record("email:newcomer", window=WINDOW)
    assert "email:newcomer" in lim._events
    assert lim.untracked_records == 0
    assert lim.retry_after("email:locked0", limit=LIMIT, window=WINDOW) == 0


def test_unlocked_keys_with_fewest_attempts_are_evicted_first(clock: list[float]) -> None:
    lim = AttemptLimiter(max_keys=10)
    for i in range(10):
        key = f"email:k{i}"
        lim.retry_after(key, limit=LIMIT, window=WINDOW)
        lim.record(key, window=WINDOW)
        if i >= 5:  # k5..k9 have two attempts, still below the limit of 3
            lim.retry_after(key, limit=LIMIT, window=WINDOW)
            lim.record(key, window=WINDOW)
    lim.record("email:newcomer", window=WINDOW)
    assert "email:newcomer" in lim._events
    assert all(f"email:k{i}" in lim._events for i in range(5, 10))
    assert any(f"email:k{i}" not in lim._events for i in range(5))


def test_one_key_cannot_grow_without_bound_and_stays_locked(clock: list[float]) -> None:
    lim = AttemptLimiter(max_keys=10)
    lim.retry_after("email:hammered", limit=LIMIT, window=WINDOW)
    for _ in range(throttle._MAX_EVENTS_PER_KEY * 3):
        lim.record("email:hammered", window=WINDOW)
    assert len(lim._events["email:hammered"]) == throttle._MAX_EVENTS_PER_KEY
    assert lim.retry_after("email:hammered", limit=LIMIT, window=WINDOW) > 0


def test_reset_and_clear_drop_all_bookkeeping(clock: list[float]) -> None:
    lim = AttemptLimiter(max_keys=10)
    _lock(lim, "email:a")
    lim.reset("email:a")
    assert "email:a" not in lim._events
    assert "email:a" not in lim._windows and "email:a" not in lim._limits
    _lock(lim, "email:b")
    lim.clear()
    assert not lim._events and not lim._windows and not lim._limits


def test_http_lockout_survives_a_flooded_table(
    client: TestClient, clock: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.throttle import login_limiter

    monkeypatch.setenv("LOGIN_MAX_FAILURES", "3")
    monkeypatch.setattr(throttle, "_MAX_KEYS", 25)
    get_settings.cache_clear()
    auth = "/api/v1/auth"
    password = "correct-horse-1"
    assert (
        client.post(
            f"{auth}/register", json={"email": "victim@example.com", "password": password}
        ).status_code
        == 201
    )
    client.post(f"{auth}/logout")
    for _ in range(3):
        wrong = client.post(
            f"{auth}/login", json={"email": "victim@example.com", "password": "wrong-password-1"}
        )
        assert wrong.status_code == 401

    _flood(login_limiter, 2_000, prefix="email:attacker")

    locked = client.post(
        f"{auth}/login", json={"email": "victim@example.com", "password": password}
    )
    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "too_many_login_attempts"
    assert len(login_limiter._events) <= 25
    get_settings.cache_clear()
