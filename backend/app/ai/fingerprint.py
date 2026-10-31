"""
Stable fingerprint of an evidence packet.

The fingerprint answers one question for a later stage: "is the evidence the
AI saw last time identical to the evidence we have now?" So it must

* be the same for the same evidence, every time, on every machine (key order,
  whitespace, tiny floating-point noise and Unicode spelling must not matter);
* change when any fact the AI would see changes;
* never depend on things that merely change over time (row ids, timestamps).

It is computed from the packet content only - never from ids or dates.
"""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from typing import Any

FINGERPRINT_PREFIX = "sha256:"
# Floats are rounded to this many significant digits before hashing, so that
# 0.30000000000000004 and 0.3 are the same fact. Six is far finer than anyone
# reading a summary could use, and far coarser than float noise.
SIGNIFICANT_DIGITS = 6


def normalize_number(value: float) -> float | None:
    """Round to ``SIGNIFICANT_DIGITS``; NaN/infinity become ``None`` (they are
    not valid JSON); negative zero becomes zero."""
    if math.isnan(value) or math.isinf(value):
        return None
    rounded = float(f"{value:.{SIGNIFICANT_DIGITS}g}")
    return 0.0 if rounded == 0 else rounded


def normalize_text(value: str) -> str:
    """Unicode NFC, so the same visible text always hashes the same."""
    return unicodedata.normalize("NFC", value)


def _canonical(value: Any) -> Any:
    # bool is checked before int/float because bool is a subclass of int.
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return normalize_number(value)
    if isinstance(value, str):
        return normalize_text(value)
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"Evidence keys must be strings, got {type(key).__name__}.")
            normalized_key = normalize_text(key)
            if normalized_key in out:
                raise ValueError(f"Two evidence keys collapse to the same text: {key!r}.")
            out[normalized_key] = _canonical(item)
        return out
    if isinstance(value, list | tuple):
        return [_canonical(item) for item in value]
    raise TypeError(f"Evidence may only hold JSON values, got {type(value).__name__}.")


def canonical_json(content: dict[str, Any]) -> str:
    """The one exact text form that is hashed and measured: sorted keys, no
    spaces, ASCII only, no NaN. List order is kept (it is meaningful)."""
    return json.dumps(
        _canonical(content),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def canonical_size_bytes(content: dict[str, Any]) -> int:
    return len(canonical_json(content).encode("utf-8"))


def fingerprint_content(content: dict[str, Any]) -> str:
    """``"sha256:<64 hex>"`` of the canonical form of ``content``."""
    digest = hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()
    return f"{FINGERPRINT_PREFIX}{digest}"
