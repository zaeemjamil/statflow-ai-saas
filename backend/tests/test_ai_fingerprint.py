"""Phase 9 Stage 1: the evidence fingerprint is stable, and sensitive to real change."""

from __future__ import annotations

import hashlib
import unicodedata

import pytest

from app.ai.fingerprint import (
    FINGERPRINT_PREFIX,
    canonical_json,
    fingerprint_content,
    normalize_number,
)

SAMPLE = {"b": [1, 2.5, None], "a": {"z": True, "y": "text"}}
SAMPLE_CANONICAL = '{"a":{"y":"text","z":true},"b":[1,2.5,null]}'
# Written down once, on purpose: if this ever changes, every stored
# fingerprint in the future is silently invalidated, so a change must be a
# deliberate decision (and a schema-version bump), not an accident.
SAMPLE_FINGERPRINT = "sha256:c7fd0072fed309ae9ad4b12d6bd7030f8494fca8d2568db58145e5ce9c205db1"


def test_canonical_form_is_exact_and_hash_matches_independent_computation() -> None:
    assert canonical_json(SAMPLE) == SAMPLE_CANONICAL
    expected = hashlib.sha256(SAMPLE_CANONICAL.encode()).hexdigest()
    assert fingerprint_content(SAMPLE) == f"sha256:{expected}"


def test_known_answer_fingerprint_never_drifts() -> None:
    assert fingerprint_content(SAMPLE) == SAMPLE_FINGERPRINT


def test_format_is_prefix_plus_64_hex() -> None:
    value = fingerprint_content(SAMPLE)
    assert value.startswith(FINGERPRINT_PREFIX)
    digest = value[len(FINGERPRINT_PREFIX) :]
    assert len(digest) == 64
    int(digest, 16)


def test_key_order_does_not_matter() -> None:
    first = {"a": 1, "b": {"c": 2, "d": 3}}
    second = {"b": {"d": 3, "c": 2}, "a": 1}
    assert fingerprint_content(first) == fingerprint_content(second)


def test_list_order_does_matter() -> None:
    assert fingerprint_content({"a": [1, 2]}) != fingerprint_content({"a": [2, 1]})


def test_floating_point_noise_is_ignored_but_real_change_is_not() -> None:
    assert fingerprint_content({"v": 0.1 + 0.2}) == fingerprint_content({"v": 0.3})
    assert fingerprint_content({"v": 0.3}) != fingerprint_content({"v": 0.31})
    # Beyond six significant digits is noise; within six is a real difference.
    assert fingerprint_content({"v": 1234567.0}) == fingerprint_content({"v": 1234567.4})
    assert fingerprint_content({"v": 1234.56}) != fingerprint_content({"v": 1234.57})


def test_nan_and_infinity_become_null_and_negative_zero_becomes_zero() -> None:
    assert fingerprint_content({"v": float("nan")}) == fingerprint_content({"v": None})
    assert fingerprint_content({"v": float("inf")}) == fingerprint_content({"v": None})
    assert fingerprint_content({"v": -0.0}) == fingerprint_content({"v": 0.0})
    assert normalize_number(float("-inf")) is None


def test_same_visible_text_in_different_unicode_spellings_is_identical() -> None:
    composed = unicodedata.normalize("NFC", "caf\u00e9")
    decomposed = unicodedata.normalize("NFD", "caf\u00e9")
    assert composed != decomposed
    assert fingerprint_content({"name": composed}) == fingerprint_content({"name": decomposed})


def test_types_that_differ_in_meaning_differ_in_hash() -> None:
    assert fingerprint_content({"v": True}) != fingerprint_content({"v": 1})
    assert fingerprint_content({"v": "1"}) != fingerprint_content({"v": 1})
    assert fingerprint_content({"v": None}) != fingerprint_content({"v": 0})


def test_output_is_ascii_even_for_non_latin_text() -> None:
    text = canonical_json({"name": "温度"})
    assert text.isascii()
    assert fingerprint_content({"name": "温度"}) != fingerprint_content({"name": "湿度"})


def test_values_that_are_not_plain_json_are_rejected() -> None:
    with pytest.raises(TypeError):
        canonical_json({"v": {1, 2}})
    with pytest.raises(TypeError):
        canonical_json({"v": object()})
    with pytest.raises(TypeError):
        canonical_json({1: "x"})  # type: ignore[dict-item]


def test_keys_that_collide_after_normalisation_are_rejected_not_merged() -> None:
    composed = unicodedata.normalize("NFC", "caf\u00e9")
    decomposed = unicodedata.normalize("NFD", "caf\u00e9")
    with pytest.raises(ValueError):
        canonical_json({composed: 1, decomposed: 2})
