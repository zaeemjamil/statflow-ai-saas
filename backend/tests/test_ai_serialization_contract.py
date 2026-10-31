"""Phase 9 Stage 1: the serialization contract of ``EvidencePacket``.

What this file does and does NOT establish
------------------------------------------
No provider integration, endpoint or other consumer of ``EvidencePacket``
exists yet. These tests therefore pin the CONTRACT that a future consumer must
follow; they do not (and cannot) prove that any future provider call is
protected. That needs a test at the real integration boundary, once one exists.

The contract:

* ``packet.canonical_json()`` is the ONLY sanctioned provider-bound text. It
  re-checks integrity first, and it is exactly the text whose SHA-256 is
  ``packet.fingerprint`` and whose byte length is ``packet.size_bytes``. The
  32,768-byte cap applies to those bytes (and only those).
* ``packet.to_json()`` is a convenience/debug rendering ONLY and is never
  provider payload text. It is integrity-checked first, but it is not the
  hashed text: for packets built by ``build_evidence`` it carries the same
  data, for arbitrary hand-made content it need not be value-identical, and
  its formatted output (notably ``indent=2``) is NOT guaranteed to stay within
  the cap, so a valid packet can render to more than 32,768 bytes.
* Reading ``packet.content`` directly is NOT verified. ``content`` stays a
  public, read-only-container attribute (many callers and tests read it), so
  reading it, ``dataclasses.asdict``, ``repr``, copies, pickles or the
  module-level ``fingerprint.canonical_json(content)`` can all hand out
  tampered content without any integrity check. That is a documented residual
  risk, pinned below so the documentation cannot silently become false.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import hashlib
import json
import pickle
import re
from pathlib import Path
from typing import Any

import pytest

from app.ai import fingerprint
from app.ai.evidence import MAX_EVIDENCE_BYTES, EvidenceIntegrityError, EvidencePacket
from tests.ai_helpers import build_both, make_analysis, sample_frame


def _built_packet() -> EvidencePacket:
    packet, _ = build_both(make_analysis(sample_frame()))
    return packet


def _hand_made(content: dict[str, Any]) -> EvidencePacket:
    return EvidencePacket(
        content=content,
        fingerprint=fingerprint.fingerprint_content(content),
        size_bytes=fingerprint.canonical_size_bytes(content),
    )


# --- the verified text is exactly what is hashed and measured ------------


def test_canonical_json_is_the_exact_text_behind_fingerprint_and_size() -> None:
    packet = _built_packet()
    text = packet.canonical_json()
    raw = text.encode("utf-8")

    # Re-derived here with hashlib directly, not via the module under test.
    assert packet.fingerprint == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert packet.size_bytes == len(raw)
    assert len(raw) <= MAX_EVIDENCE_BYTES
    assert text.isascii()
    # Compact, sorted, ASCII form: re-dumping the parsed text changes nothing.
    assert text == json.dumps(
        json.loads(text), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def test_canonical_json_is_deterministic_across_independent_builds() -> None:
    first, second = _built_packet(), _built_packet()
    assert first is not second
    assert first.canonical_json() == second.canonical_json()
    assert first.fingerprint == second.fingerprint
    assert first.size_bytes == second.size_bytes


def test_to_json_carries_the_same_data_as_canonical_json_for_built_packets() -> None:
    packet = _built_packet()
    assert json.loads(packet.to_json()) == json.loads(packet.canonical_json())
    assert json.loads(packet.to_json(indent=2)) == json.loads(packet.canonical_json())


def test_to_json_is_not_the_hashed_text_for_unnormalized_content() -> None:
    # Characterization of a documented distinction, not an endorsement: the
    # fingerprint hashes NFC text and floats rounded to 6 significant digits.
    # `to_json` dumps the stored values as they are. Built packets are
    # already normalized, so for them the two agree (test above); a packet
    # made from raw content can differ. Provider-bound text is therefore
    # `canonical_json()` only; `to_json()` is a convenience/debug rendering.
    packet = _hand_made({"schema_version": 2, "x": 0.30000000000000004, "note": "e\u0301"})
    assert json.loads(packet.canonical_json())["x"] == 0.3
    assert json.loads(packet.to_json())["x"] == 0.30000000000000004
    assert json.loads(packet.canonical_json())["note"] == "\u00e9"
    assert json.loads(packet.to_json())["note"] == "e\u0301"


# --- the cap binds the canonical bytes, not to_json() output -------------


def _many_columns_content(columns: int = 500) -> dict[str, Any]:
    # Deterministic and independent of the analytics output: canonical form is
    # about 20 KB (valid), but indented rendering is well over 32 KB.
    return {
        "schema_version": 2,
        "columns": [{"column": f"Column_{i:03d}", "type": "numeric"} for i in range(columns)],
        "warnings": [],
    }


def test_the_cap_binds_canonical_json_bytes_and_not_formatted_to_json_output() -> None:
    packet = _hand_made(_many_columns_content())
    packet.verify_integrity()  # a valid packet: it was accepted at construction

    canonical = packet.canonical_json().encode("utf-8")
    assert len(canonical) == packet.size_bytes <= MAX_EVIDENCE_BYTES

    # The same valid packet, rendered for reading, is over the cap. So the cap
    # is a property of canonical_json() only; to_json() must never be sent.
    formatted = packet.to_json(indent=2).encode("utf-8")
    assert len(formatted) > MAX_EVIDENCE_BYTES
    assert len(formatted) > len(canonical)
    assert formatted != canonical


def test_to_json_text_is_not_the_fingerprinted_or_measured_text() -> None:
    packet = _hand_made(_many_columns_content())
    for rendering in (packet.to_json(), packet.to_json(indent=2)):
        raw = rendering.encode("utf-8")
        assert packet.fingerprint != "sha256:" + hashlib.sha256(raw).hexdigest()
        assert packet.size_bytes != len(raw)
    canonical = packet.canonical_json().encode("utf-8")
    assert packet.fingerprint == "sha256:" + hashlib.sha256(canonical).hexdigest()
    assert packet.size_bytes == len(canonical)


# --- the documentation must not present to_json() as the provider payload -


def _flat(text: str | None) -> str:
    assert text, "expected a docstring"
    return " ".join(text.split())


def test_docstrings_name_canonical_json_as_the_only_provider_bound_text() -> None:
    cls, canonical, formatted = (
        _flat(EvidencePacket.__doc__),
        _flat(EvidencePacket.canonical_json.__doc__),
        _flat(EvidencePacket.to_json.__doc__),
    )
    assert "ONLY sanctioned provider-bound text" in canonical
    assert "32,768-byte cap applies" in canonical
    assert "NOT provider-bound payload text" in formatted
    assert (
        "indent=2" in formatted and "NOT guaranteed to stay within the 32,768-byte cap" in formatted
    )
    assert "``canonical_json()`` is the ONLY sanctioned provider-bound serialized text" in cls
    assert "NOT PROVIDER-BOUND: ``to_json()``" in cls
    # The pre-6g wording that made either serializer look like a send path.
    assert "Anything meant to leave the application must go through them" not in cls


def test_recovery_notes_do_not_tell_a_provider_to_use_to_json() -> None:
    recovery = Path(__file__).resolve().parents[2] / "RECOVERY.md"
    if not recovery.is_file():
        pytest.skip("RECOVERY.md is not part of this checkout")
    text = " ".join(recovery.read_text(encoding="utf-8").split())
    assert (
        re.search(r"provider[^.]{0,80}(must|should|may) use[^.]{0,40}to_json", text, re.I) is None
    )


# --- the sanctioned serializers refuse a tampered real packet ------------


def test_a_tampered_built_packet_cannot_be_serialized_by_either_serializer() -> None:
    packet = _built_packet()
    clean = packet.canonical_json()
    list.append(packet.content["columns"], {"column": "Real Customer Name"})
    for call in (packet.canonical_json, packet.to_json, lambda: packet.to_json(indent=2)):
        with pytest.raises(EvidenceIntegrityError):
            call()
    assert "Real Customer Name" not in clean


# --- pinned: the access paths that do NOT verify (documented residual) ---


def _tampered_hand_made() -> EvidencePacket:
    packet = _hand_made({"schema_version": 2, "columns": [], "warnings": []})
    dict.__setitem__(packet.content, "injected", "ZZ_INJECTED")
    with pytest.raises(EvidenceIntegrityError):
        packet.verify_integrity()  # confirm it really is tampered
    return packet


def test_direct_content_access_does_not_verify_and_is_documented_as_such() -> None:
    packet = _tampered_hand_made()
    unverified_paths: dict[str, Any] = {
        "json.dumps(packet.content)": lambda: json.dumps(packet.content),
        "fingerprint.canonical_json(packet.content)": lambda: fingerprint.canonical_json(
            packet.content
        ),
        "dataclasses.asdict(packet)": lambda: json.dumps(dataclasses.asdict(packet)),
        "dict(packet.content)": lambda: json.dumps(dict(packet.content)),
        "repr(packet)": lambda: repr(packet),
        "copy.copy(packet)": lambda: json.dumps(copy.copy(packet).content),
        "pickle round trip": lambda: json.dumps(pickle.loads(pickle.dumps(packet)).content),
    }
    for label, produce in unverified_paths.items():
        assert "ZZ_INJECTED" in produce(), f"{label} unexpectedly verified or dropped content"


def test_replace_is_a_verified_path_unlike_copy() -> None:
    packet = _tampered_hand_made()
    with pytest.raises(EvidenceIntegrityError):
        dataclasses.replace(packet)


# --- tripwire: no packet-handling production code reads content directly -

_APP_DIR = Path(__file__).resolve().parents[1] / "app"
_AI_DIR = _APP_DIR / "ai"
_DEFINING_MODULE = _AI_DIR / "evidence.py"


def _imports_app_ai(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name == "app.ai" or a.name.startswith("app.ai.") for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module == "app.ai" or node.module.startswith("app.ai."):
                return True
            if node.module == "app" and any(a.name == "ai" for a in node.names):
                return True
    return False


def _risky_uses(source: str, *, in_ai_package: bool = False) -> list[str]:
    """Lines that read ``.content``, call ``.to_json`` or use ``asdict`` /
    ``astuple`` in a module that can hold an ``EvidencePacket``.

    Scope is decided by IMPORTS, not by types: only code under ``app/ai`` or
    importing from ``app.ai`` is checked, so unrelated modules (HTTP responses,
    uploads, ...) are never flagged. Deliberately simple and imperfect: inside a
    checked module ANY ``.content`` is flagged (a provider client's
    ``response.content`` will need a conscious decision), and ``getattr``,
    ``vars``, ``__dict__`` and ``repr`` are not detected."""
    tree = ast.parse(source)
    if not (in_ai_package or _imports_app_ai(tree)):
        return []
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"content", "to_json"}:
            found.append(f"{node.lineno} .{node.attr}")
        if isinstance(node, ast.Attribute | ast.Name):
            name = node.attr if isinstance(node, ast.Attribute) else node.id
            if name in {"asdict", "astuple"}:
                found.append(f"{node.lineno} {name}")
    return found


def _production_modules() -> list[Path]:
    return sorted(p for p in _APP_DIR.rglob("*.py") if p != _DEFINING_MODULE)


def test_no_packet_handling_production_code_reads_content_or_uses_to_json() -> None:
    # A tripwire, not protection. Today nothing outside evidence.py reads
    # `.content`, calls `to_json` (a debug rendering) or dumps the dataclass;
    # if something starts to, this fails and forces a review of whether what it
    # sends is `canonical_json()`.
    offenders: list[str] = []
    for path in _production_modules():
        found = _risky_uses(path.read_text(encoding="utf-8"), in_ai_package=_AI_DIR in path.parents)
        offenders.extend(f"{path.relative_to(_APP_DIR)}:{item}" for item in found)
    assert offenders == []


def test_tripwire_scans_a_real_set_of_modules() -> None:
    # Guards the tripwire against silently scanning nothing (e.g. a moved dir
    # or an import detector that no longer recognises the real imports).
    scanned = {p.name for p in _production_modules()}
    assert {"loader.py", "fingerprint.py", "main.py"} <= scanned
    assert _DEFINING_MODULE.is_file()
    loader = ast.parse((_AI_DIR / "loader.py").read_text(encoding="utf-8"))
    assert _imports_app_ai(loader)


@pytest.mark.parametrize(
    ("source", "flagged"),
    [
        pytest.param(
            "from app.ai.loader import evidence_packet_for_analysis\n\n"
            "def f(packet):\n    return packet.content\n",
            True,
            id="packet.content in a module importing app.ai",
        ),
        pytest.param(
            "from app.ai.evidence import EvidencePacket\n\n"
            "def f(p):\n    return p.to_json(indent=2)\n",
            True,
            id="to_json in a module importing app.ai",
        ),
        pytest.param(
            "import dataclasses\nfrom app.ai import evidence\n\n"
            "def f(p):\n    return dataclasses.asdict(p)\n",
            True,
            id="asdict in a module importing app.ai",
        ),
        pytest.param(
            "def f(response):\n    return response.content\n",
            False,
            id="unrelated response.content, no app.ai import: NOT flagged",
        ),
        pytest.param(
            "from app.services import file_service\n\ndef f(upload):\n    return upload.content\n",
            False,
            id="unrelated module importing other app code: NOT flagged",
        ),
        pytest.param(
            "from app.ai.loader import evidence_packet_for_analysis\n\n"
            "def f(response):\n    return response.content\n",
            True,
            id="KNOWN false positive: response.content inside a packet-handling module",
        ),
        pytest.param(
            "from app.ai.evidence import EvidencePacket\n\n"
            "def f(p):\n    return getattr(p, 'content'), vars(p), p.__dict__, repr(p)\n",
            False,
            id="KNOWN gap: getattr / vars / __dict__ / repr are not detected",
        ),
    ],
)
def test_tripwire_scoping_and_its_documented_limits(source: str, flagged: bool) -> None:
    assert bool(_risky_uses(source)) is flagged


def test_tripwire_always_checks_code_inside_the_ai_package() -> None:
    # Relative imports inside app/ai have no `app.ai` import to detect.
    assert _risky_uses("def f(p):\n    return p.content\n", in_ai_package=True)
    assert not _risky_uses("def f(p):\n    return p.content\n", in_ai_package=False)
