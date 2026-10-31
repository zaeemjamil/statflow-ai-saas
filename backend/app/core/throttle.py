"""Small in-memory attempt limiter (sliding window) for brute-force protection.

Per server process: with N worker processes the effective limit is up to N times
higher, which is still a strong brake on guessing. State is lost on restart.

Memory is bounded three ways: expired entries are purged, each key keeps at most
``_MAX_EVENTS_PER_KEY`` timestamps, and the table has a hard cap of ``_MAX_KEYS``
keys.

Table-capacity policy (what happens when a NEW key arrives and the table is full):

1. Expired keys are purged first.
2. If it is still full, the least valuable keys are evicted, down to a low-water
   mark (so the cost of the scan is shared by many later inserts). "Least valuable"
   means: not currently locked out, fewest recent events first, oldest activity
   first.
3. A key that is CURRENTLY LOCKED OUT (its event count in the window has reached
   the limit last passed to ``retry_after``) is never evicted. The table is never
   cleared.
4. If every key is an active lockout, the new key is not tracked (it is counted in
   ``untracked_records``) instead of dropping a lockout. Memory stays bounded and
   existing lockouts stay in force.

A key whose limit has never been seen (neither ``retry_after`` nor ``record(limit=)``
called with it) is treated as not locked, so it can be evicted. Both call sites call
``retry_after`` before ``record``; the only gap is the very first attempt for a key
when the limit is 1, which is protected from the next ``retry_after`` on.
"""

from __future__ import annotations

import heapq
import threading
import time
from collections import deque

_MAX_KEYS = 50_000
# Never keep more than this many timestamps for one key. Far above any limit in
# use (login: 8 / 40, reset: 5 / 20), so a key at its limit stays at its limit.
_MAX_EVENTS_PER_KEY = 1_000
# When full, evict down to this share of capacity so a scan is not repeated on
# every insert.
_LOW_WATER = 0.9


class AttemptLimiter:
    def __init__(self, *, max_keys: int | None = None) -> None:
        self._lock = threading.Lock()
        self._max_keys = max_keys  # None: read the module constant at call time
        self._events: dict[str, deque[float]] = {}
        self._windows: dict[str, float] = {}
        self._limits: dict[str, int] = {}
        self.untracked_records = 0

    # -- internals (call with the lock held) ---------------------------------

    def _capacity(self) -> int:
        return self._max_keys if self._max_keys is not None else _MAX_KEYS

    def _drop(self, key: str) -> None:
        self._events.pop(key, None)
        self._windows.pop(key, None)
        self._limits.pop(key, None)

    def _prune(self, key: str, window: float, now: float) -> deque[float] | None:
        """Drop expired timestamps; remove the key when none are left."""
        events = self._events.get(key)
        if events is None:
            return None
        while events and now - events[0] > window:
            events.popleft()
        if not events:
            self._drop(key)
            return None
        return events

    def _is_locked(self, key: str) -> bool:
        """Lock state of an already-pruned key (does not modify the table)."""
        events = self._events.get(key)
        limit = self._limits.get(key)
        return events is not None and limit is not None and len(events) >= limit

    def _make_room(self, now: float) -> bool:
        """Free at least one slot without touching an active lockout.

        Returns False when every tracked key is an active lockout."""
        capacity = self._capacity()
        if len(self._events) < capacity:
            return True
        for key in list(self._events):
            self._prune(key, self._windows.get(key, 0.0), now)
        if len(self._events) < capacity:
            return True
        evictable = [
            (len(events), events[-1], key)
            for key, events in list(self._events.items())
            if not self._is_locked(key)
        ]
        want = len(self._events) - int(capacity * _LOW_WATER)
        for _count, _last, key in heapq.nsmallest(max(1, want), evictable):
            self._drop(key)
        return len(self._events) < capacity

    # -- public API ----------------------------------------------------------

    def retry_after(self, key: str, *, limit: int, window: float) -> int:
        """Seconds until another attempt is allowed (0 = allowed now)."""
        now = time.monotonic()
        with self._lock:
            events = self._prune(key, window, now)
            if events is None:
                return 0
            self._windows[key] = window
            self._limits[key] = limit
            if len(events) < limit:
                return 0
            return max(1, int(window - (now - events[0])) + 1)

    def record(self, key: str, *, window: float, limit: int | None = None) -> None:
        """Record one attempt. ``limit`` is optional: pass it when known so the key
        is protected from eviction as soon as it reaches that limit."""
        now = time.monotonic()
        with self._lock:
            events = self._events.get(key)
            if events is None:
                if not self._make_room(now):
                    self.untracked_records += 1  # table is all active lockouts
                    return
                events = deque(maxlen=_MAX_EVENTS_PER_KEY)
                self._events[key] = events
            self._windows[key] = max(window, self._windows.get(key, 0.0))
            if limit is not None:
                self._limits[key] = limit
            events.append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._drop(key)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._windows.clear()
            self._limits.clear()
            self.untracked_records = 0


login_limiter = AttemptLimiter()
reset_limiter = AttemptLimiter()
