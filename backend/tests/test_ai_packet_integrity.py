"""Phase 9 Stage 1: an EvidencePacket cannot be changed after it is built.

Before this correction ``content`` was a plain dict, so
``packet.content["columns"].append(...)`` silently changed the evidence that
would be sent while ``fingerprint`` and ``size_bytes`` kept describing the OLD
content (and the 32,768-byte cap could be exceeded after the check). These
tests use small hand-written content on purpose: they test the packet class
itself, not the analytics pipeline."""

from __future__ import annotations

import copy
import dataclasses
import json
import pickle
from typing import Any

import pytest

from app.ai import evidence
from app.ai.evidence import MAX_EVIDENCE_BYTES, EvidenceIntegrityError, EvidencePacket
from app.ai.fingerprint import canonical_json, fingerprint_content


def _content() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "dataset": {"rows_uploaded": 40, "columns_uploaded": 2},
        "warnings": [],
        "columns": [
            {"column": "Column_001", "type": "numeric", "min": 0.5},
            {"column": "Column_002", "type": "categorical"},
        ],
        "omitted": [{"section": "columns", "shown": 1, "total": 2}],
    }


def _packet(content: dict[str, Any] | None = None) -> EvidencePacket:
    data = content if content is not None else _content()
    return EvidencePacket(
        content=data,
        fingerprint=fingerprint_content(data),
        size_bytes=len(canonical_json(data).encode("utf-8")),
    )


# --- ordinary mutation is refused, at every depth ------------------------


def test_content_cannot_be_changed_at_the_top_level() -> None:
    packet = _packet()
    with pytest.raises(TypeError):
        packet.content["injected"] = 1
    with pytest.raises(TypeError):
        packet.content["dataset"] = {}
    with pytest.raises(TypeError):
        del packet.content["dataset"]
    with pytest.raises(TypeError):
        packet.content.update({"x": 1})
    with pytest.raises(TypeError):
        packet.content.setdefault("x", 1)
    with pytest.raises(TypeError):
        packet.content.pop("dataset")
    with pytest.raises(TypeError):
        packet.content.popitem()
    with pytest.raises(TypeError):
        packet.content.clear()
    with pytest.raises(TypeError):
        packet.content.__ior__({"x": 1})
    assert packet.content == _content()


def test_content_cannot_be_changed_in_nested_dicts_and_lists() -> None:
    packet = _packet()
    with pytest.raises(TypeError):
        packet.content["dataset"]["rows_uploaded"] = 999
    with pytest.raises(TypeError):
        packet.content["columns"][0]["type"] = "ZZ"
    with pytest.raises(TypeError):
        packet.content["columns"][0].update(min=1)
    with pytest.raises(TypeError):
        packet.content["columns"].append({"column": "Column_003"})
    with pytest.raises(TypeError):
        packet.content["columns"].extend([{"column": "Column_003"}])
    with pytest.raises(TypeError):
        packet.content["columns"].insert(0, {})
    with pytest.raises(TypeError):
        packet.content["columns"].pop()
    with pytest.raises(TypeError):
        packet.content["columns"].remove(packet.content["columns"][0])
    with pytest.raises(TypeError):
        packet.content["columns"].sort(key=lambda c: c["column"])
    with pytest.raises(TypeError):
        packet.content["columns"].reverse()
    with pytest.raises(TypeError):
        packet.content["columns"].clear()
    with pytest.raises(TypeError):
        packet.content["columns"][0] = {}
    with pytest.raises(TypeError):
        del packet.content["columns"][0]
    with pytest.raises(TypeError):
        packet.content["columns"] += [{}]
    with pytest.raises(TypeError):
        packet.content["columns"] *= 2
    assert packet.content == _content()
    assert packet.canonical_json() == canonical_json(_content())


def test_the_original_dict_handed_in_is_not_shared_with_the_packet() -> None:
    source = _content()
    packet = _packet(source)
    source["dataset"]["rows_uploaded"] = 12345  # the caller's own dict
    source["columns"].append({"column": "Column_777"})
    assert packet.content["dataset"]["rows_uploaded"] == 40
    assert len(packet.content["columns"]) == 2
    packet.verify_integrity()


def test_the_packet_attributes_cannot_be_reassigned() -> None:
    packet = _packet()
    with pytest.raises(dataclasses.FrozenInstanceError):
        packet.content = {}  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        packet.fingerprint = "sha256:" + "0" * 64  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        packet.size_bytes = 1  # type: ignore[misc]


# --- a stale size/fingerprint or an oversized packet cannot be built -----


def test_construction_rejects_a_stale_size() -> None:
    data = _content()
    good = len(canonical_json(data).encode("utf-8"))
    for wrong in (good - 1, good + 1, 0):
        with pytest.raises(EvidenceIntegrityError):
            EvidencePacket(content=data, fingerprint=fingerprint_content(data), size_bytes=wrong)


def test_construction_rejects_a_stale_fingerprint() -> None:
    data = _content()
    other = _content()
    other["dataset"]["rows_uploaded"] = 41
    with pytest.raises(EvidenceIntegrityError):
        EvidencePacket(
            content=data,
            fingerprint=fingerprint_content(other),
            size_bytes=len(canonical_json(data).encode("utf-8")),
        )


def test_construction_rejects_content_over_the_cap_even_with_matching_metadata() -> None:
    assert MAX_EVIDENCE_BYTES == 32_768
    data = _content()
    data["padding"] = "a" * MAX_EVIDENCE_BYTES  # canonical size is now above the cap
    size = len(canonical_json(data).encode("utf-8"))
    assert size > MAX_EVIDENCE_BYTES
    with pytest.raises(EvidenceIntegrityError):
        EvidencePacket(content=data, fingerprint=fingerprint_content(data), size_bytes=size)


def test_the_cap_boundary_is_exact() -> None:
    data = _content()
    data["padding"] = ""
    base = len(canonical_json(data).encode("utf-8"))
    data["padding"] = "a" * (MAX_EVIDENCE_BYTES - base)  # exactly at the cap
    assert len(canonical_json(data).encode("utf-8")) == MAX_EVIDENCE_BYTES
    assert _packet(data).size_bytes == MAX_EVIDENCE_BYTES
    data["padding"] += "a"  # one byte over
    with pytest.raises(EvidenceIntegrityError):
        _packet(data)


def test_content_that_is_not_json_is_rejected() -> None:
    data = _content()
    data["bad"] = {1, 2, 3}  # a set is not JSON
    with pytest.raises(EvidenceIntegrityError):
        EvidencePacket(content=data, fingerprint="sha256:" + "0" * 64, size_bytes=1)


def test_replace_cannot_produce_a_packet_with_stale_metadata() -> None:
    packet = _packet()
    changed = _content()
    changed["dataset"]["rows_uploaded"] = 1
    with pytest.raises(EvidenceIntegrityError):
        dataclasses.replace(packet, content=changed)  # old fingerprint and size kept
    rebuilt = _packet(changed)  # the supported way: a fully new packet
    assert rebuilt.fingerprint != packet.fingerprint


# --- tampering that gets around the read-only containers is caught -------


def _tamper_nested_value(packet: EvidencePacket) -> None:
    dict.__setitem__(packet.content["dataset"], "rows_uploaded", 999)


def _tamper_append(packet: EvidencePacket) -> None:
    list.append(packet.content["columns"], {"column": "Column_999"})


def _tamper_top_level(packet: EvidencePacket) -> None:
    dict.__setitem__(packet.content, "injected", "ZZ_INJECTED")


def _tamper_oversize(packet: EvidencePacket) -> None:
    dict.__setitem__(packet.content, "padding", "a" * (MAX_EVIDENCE_BYTES + 100))


def _tamper_same_size(packet: EvidencePacket) -> None:
    # Same byte length, different value: only the fingerprint can notice.
    dict.__setitem__(packet.content["columns"][0], "type", "numerid")


def _tamper_non_json(packet: EvidencePacket) -> None:
    dict.__setitem__(packet.content, "bad", {1})


@pytest.mark.parametrize(
    "tamper",
    [
        _tamper_nested_value,
        _tamper_append,
        _tamper_top_level,
        _tamper_oversize,
        _tamper_same_size,
        _tamper_non_json,
    ],
)
def test_tampering_around_the_containers_is_detected_by_every_serializer(
    tamper: Any,
) -> None:
    packet = _packet()
    tamper(packet)
    with pytest.raises(EvidenceIntegrityError):
        packet.verify_integrity()
    with pytest.raises(EvidenceIntegrityError):
        packet.canonical_json()
    with pytest.raises(EvidenceIntegrityError):
        packet.to_json()
    with pytest.raises(EvidenceIntegrityError):
        packet.to_json(indent=2)


def test_swapping_the_content_attribute_itself_is_detected() -> None:
    packet = _packet()
    other = _content()
    other["dataset"]["rows_uploaded"] = 7
    object.__setattr__(packet, "content", other)  # deliberately bypassing the freeze
    with pytest.raises(EvidenceIntegrityError):
        packet.canonical_json()


# --- serialization is deterministic and unchanged ------------------------


def test_serialization_and_fingerprint_are_identical_to_the_plain_dict_form() -> None:
    plain = _content()
    packet = _packet(plain)
    assert packet.canonical_json() == canonical_json(plain)
    assert packet.fingerprint == fingerprint_content(plain)
    assert packet.fingerprint == _packet(_content()).fingerprint  # deterministic
    assert json.loads(packet.to_json()) == plain
    assert packet.to_json() == json.dumps(plain, ensure_ascii=False, sort_keys=True)
    assert packet.to_json(indent=2) == json.dumps(
        plain, ensure_ascii=False, sort_keys=True, indent=2
    )
    # Key order of the input does not matter.
    reordered = dict(reversed(list(plain.items())))
    assert _packet(reordered).canonical_json() == packet.canonical_json()
    assert _packet(reordered).fingerprint == packet.fingerprint
    assert packet.content == plain  # frozen containers still compare equal to plain ones
    assert isinstance(packet.content, dict)
    assert isinstance(packet.content["columns"], list)


def test_copies_pickles_and_asdict_stay_read_only_and_equal() -> None:
    packet = _packet()
    for twin in (
        copy.copy(packet),
        copy.deepcopy(packet),
        pickle.loads(pickle.dumps(packet)),
    ):
        assert twin == packet
        assert twin.fingerprint == packet.fingerprint
        twin.verify_integrity()
        with pytest.raises(TypeError):
            twin.content["columns"].append({})
        with pytest.raises(TypeError):
            twin.content["dataset"]["rows_uploaded"] = 0
    deep = copy.deepcopy(packet.content)
    with pytest.raises(TypeError):
        deep["columns"].append({})
    as_dict = dataclasses.asdict(packet)
    assert json.loads(json.dumps(as_dict))["fingerprint"] == packet.fingerprint
    # A caller who wants a mutable working copy gets one explicitly, and it is not the packet.
    working = json.loads(packet.to_json())
    working["dataset"]["rows_uploaded"] = 0
    assert packet.content["dataset"]["rows_uploaded"] == 40
    packet.verify_integrity()


def test_verification_uses_the_current_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    packet = _packet()
    monkeypatch.setattr(evidence, "MAX_EVIDENCE_BYTES", packet.size_bytes - 1)
    with pytest.raises(EvidenceIntegrityError):
        packet.canonical_json()
    monkeypatch.setattr(evidence, "MAX_EVIDENCE_BYTES", packet.size_bytes)
    assert packet.canonical_json() == canonical_json(_content())
