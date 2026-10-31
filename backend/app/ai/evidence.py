"""
Evidence packet builder.

Turns a persisted ``AnalysisPublic`` (the very object the dashboard shows)
into the one, size-bounded JSON document that a later stage may give to the AI
Analyst. Because it is built from the persisted analysis and nothing else, an
explanation can only ever quote numbers the user can also see on screen.

What is deliberately NOT in the packet:

* ORIGINAL COLUMN NAMES. Every column is an alias (``Column_001`` ...), used
  identically in every section, including notes and chart titles. Sanitizing a
  name is not anonymizing it, so names are never copied, cleaned or truncated
  into the packet. The original <-> alias mapping stays local, in
  ``EvidenceBuild.aliases`` (see ``aliases.py``), a different object from the
  provider-facing ``EvidencePacket``; it is not part of ``content`` and not
  part of the fingerprint. Sheet names are omitted too.
* raw rows or cell values (no sample predictions, no outlier row positions,
  no "examples" of badly formatted values, no text fill values such as a most
  common category);
* EXACT MINIMUM AND MAXIMUM VALUES. A column's smallest and largest value are
  real cells of the dataset, so ``min`` / ``max`` are withheld from both the
  ``columns`` and the ``statistics`` sections (``WITHHELD_STATISTICS_FIELDS``).
  The spread is still described by the median, quartiles, IQR, standard
  deviation and the outlier bounds;
* ids (project, file, analysis), timestamps, the file name or the project name;
* chart point data and the full correlation matrix (large, and derivable);
* the free text of import notes and chart titles. Those strings can quote
  column names, sheet names or cell values, so they are rebuilt from fixed
  templates using aliases and numbers only. Every other string is either an
  alias, a fixed template, or a member of a CLOSED vocabulary (see the
  ``*_VALUES`` sets below). A value outside its vocabulary is replaced by a
  safe constant or left out; it is never passed through, whatever it looks like.

What IS sent (the whole of it, so the user-facing wording can be exact): anonymous
column aliases; counts (rows, columns, missing cells, duplicate rows, unique values
per column, outliers); column types; summary statistics per numeric column (mean,
median, standard deviation, quartiles, IQR); the strongest correlation pairs;
outlier bounds; cleaning counts and numeric fill values (medians); regression
settings, metrics, coefficients and a residual summary; and fixed-template text.
These are aggregates, not rows, but an aggregate can coincide with a real value
(a median of an odd number of values is one of them), so the wording is "no
individual rows, and no exact minimum or maximum", never "no values".

Size: the packet is capped at ``MAX_EVIDENCE_BYTES`` (canonical JSON). Long
lists are cut deterministically and every cut is recorded in ``omitted`` so
the AI is told, truthfully, that it is looking at part of the picture. If even
the smallest form does not fit, no packet is produced.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from typing import Any, NoReturn

from app.ai.aliases import AMBIGUOUS_ALIAS, ColumnAliasMap
from app.ai.eligibility import (
    EVIDENCE_TOO_LARGE,
    SMALL_SAMPLE,
    SMALL_SAMPLE_ROWS,
    EligibilityResult,
    EvidenceNotEligible,
    check_eligibility,
)
from app.ai.fingerprint import canonical_json, fingerprint_content, normalize_text
from app.schemas.analysis import AnalysisPublic

# Bump when the *shape or meaning* of the packet changes, so every stored
# fingerprint from the old shape is recognisably out of date.
# 2: column names replaced by aliases; notes/chart titles templated; `warnings`.
# 3: exact min/max withheld from `columns` and `statistics`.
EVIDENCE_SCHEMA_VERSION = 3

# Hard ceiling for the canonical JSON form (about 8k tokens of English).
MAX_EVIDENCE_BYTES = 32_768

MAX_TEXT_CHARS = 400

# Warning code: two or more columns have the exact same name.
DUPLICATE_COLUMN_NAMES = "duplicate_column_names_ambiguous_references"

# Shown where a name unexpectedly has no alias. Fails safe: nothing leaks.
UNMAPPED_ALIAS = "Column_unmapped"

# CLOSED VOCABULARIES. Every enum-like string in the packet must be a member
# of one of these sets. The shape of a string ("looks like a label") proves
# nothing: a column named ``ZZ_REVENUE_Q3`` looks exactly like a label. Values
# outside a set are replaced by the safe constant (UNKNOWN_VALUE) or omitted.
# They mirror what the analytics engine can produce today; a new engine value
# must be added here on purpose, and until then it is reported as "unknown".
UNKNOWN_VALUE = "unknown"

# Statistics fields that are real cells of the dataset (its smallest and largest
# value). They are never copied into the packet.
WITHHELD_STATISTICS_FIELDS = frozenset({"min", "max"})

COLUMN_CLASSIFICATION_VALUES = frozenset({"numeric", "categorical", "date"})
NUMBER_FORMAT_VALUES = frozenset({"currency", "percent", "thousands"})
DATE_ISSUE_VALUES = frozenset({"ambiguous", "inconsistent", "partly_ambiguous"})
IMPORT_NOTE_SEVERITY_VALUES = frozenset({"info", "warning"})
IMPORT_NOTE_CODE_VALUES = frozenset(
    {
        "na_text_read_as_missing",
        "na_text_kept_as_value",
        "blank_headers",
        "duplicate_headers",
        "likely_identifier_columns",
        "formatted_numbers_as_text",
        "ambiguous_dates",
        "xlsx_extra_sheets",
    }
)
CLEANING_ACTION_VALUES = frozenset({"imputed", "left_unchanged"})
CLEANING_METHOD_VALUES = frozenset({"median", "mode"})
CLEANING_REASON_VALUES = frozenset({"no_non_missing_values", "strategy_unchanged"})
REGRESSION_METHOD_VALUES = frozenset({"ols"})
OUTLIER_METHOD_VALUES = frozenset({"iqr"})
CHART_TYPE_VALUES = frozenset({"scatter", "line", "bar", "histogram", "count"})
CORRELATION_STRENGTH_VALUES = frozenset({"strong", "moderate", "weak", "negligible"})
CORRELATION_DIRECTION_VALUES = frozenset({"positive", "negative"})
RESIDUAL_SUMMARY_KEYS = frozenset({"mean", "std", "min", "max"})


@dataclass(frozen=True)
class _Caps:
    """How many items of each list may be included."""

    columns: int
    statistics: int
    notes: int
    note_columns: int
    cleaning_actions: int
    correlation_pairs: int
    outlier_columns: int
    coefficients: int
    predictors: int
    charts: int
    skipped_names: int


# Tried in order; the first whose result fits under MAX_EVIDENCE_BYTES wins.
# Fixed tiers (rather than trimming "until it fits") keep the result simple
# to reason about and exactly repeatable.
_TIERS: tuple[_Caps, ...] = (
    _Caps(60, 40, 12, 10, 40, 15, 20, 20, 20, 12, 20),
    _Caps(40, 30, 10, 8, 25, 12, 15, 15, 15, 6, 15),
    _Caps(25, 20, 8, 6, 15, 8, 10, 10, 10, 0, 10),
    _Caps(12, 12, 5, 4, 8, 5, 6, 8, 8, 0, 5),
)


class EvidenceIntegrityError(ValueError):
    """The packet's content no longer matches its saved size/fingerprint, or
    exceeds ``MAX_EVIDENCE_BYTES``. Raised instead of serializing it."""


def _read_only() -> NoReturn:
    raise TypeError("Evidence content is read-only; build a new packet instead.")


class _FrozenDict(dict[str, Any]):
    """A dict that refuses every in-place change (still a real ``dict``, so
    ``json.dumps``, ``==`` and ``dataclasses.asdict`` work unchanged)."""

    __slots__ = ()

    def __setitem__(self, *args: Any, **kwargs: Any) -> NoReturn:
        _read_only()

    def __delitem__(self, *args: Any, **kwargs: Any) -> NoReturn:
        _read_only()

    def __ior__(self, *args: Any, **kwargs: Any) -> NoReturn:  # type: ignore[misc]
        _read_only()

    def clear(self, *args: Any, **kwargs: Any) -> NoReturn:
        _read_only()

    def pop(self, *args: Any, **kwargs: Any) -> NoReturn:
        _read_only()

    def popitem(self, *args: Any, **kwargs: Any) -> NoReturn:
        _read_only()

    def setdefault(self, *args: Any, **kwargs: Any) -> NoReturn:
        _read_only()

    def update(self, *args: Any, **kwargs: Any) -> NoReturn:
        _read_only()

    def __reduce__(self) -> tuple[Any, ...]:  # copy / deepcopy / pickle
        return (_FrozenDict, (dict(self),))


class _FrozenList(list[Any]):
    """A list that refuses every in-place change (still a real ``list``)."""

    __slots__ = ()

    def __setitem__(self, *args: Any, **kwargs: Any) -> NoReturn:
        _read_only()

    def __delitem__(self, *args: Any, **kwargs: Any) -> NoReturn:
        _read_only()

    def __iadd__(self, *args: Any, **kwargs: Any) -> NoReturn:  # type: ignore[misc]
        _read_only()

    def __imul__(self, *args: Any, **kwargs: Any) -> NoReturn:  # type: ignore[misc]
        _read_only()

    def append(self, *args: Any, **kwargs: Any) -> NoReturn:
        _read_only()

    def clear(self, *args: Any, **kwargs: Any) -> NoReturn:
        _read_only()

    def extend(self, *args: Any, **kwargs: Any) -> NoReturn:
        _read_only()

    def insert(self, *args: Any, **kwargs: Any) -> NoReturn:
        _read_only()

    def pop(self, *args: Any, **kwargs: Any) -> NoReturn:
        _read_only()

    def remove(self, *args: Any, **kwargs: Any) -> NoReturn:
        _read_only()

    def reverse(self, *args: Any, **kwargs: Any) -> NoReturn:
        _read_only()

    def sort(self, *args: Any, **kwargs: Any) -> NoReturn:
        _read_only()

    def __reduce__(self) -> tuple[Any, ...]:
        return (_FrozenList, (list(self),))


def _freeze(value: Any) -> Any:
    """Deep read-only copy of JSON-like data (dicts and lists, at every depth)."""
    if isinstance(value, dict):
        return _FrozenDict({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list | tuple):
        return _FrozenList(_freeze(v) for v in value)
    return value


@dataclass(frozen=True)
class EvidencePacket:
    """The PROVIDER-FACING object: exactly what may leave the application.

    ``content`` is exactly what is hashed; ``fingerprint`` and ``size_bytes``
    are derived from it. It holds no column names and no reference to the
    alias mapping, so serializing or passing the whole object cannot expose
    either.

    Integrity (so the saved size and fingerprint can never go stale):

    * on construction the content is copied into read-only containers (a
      change at any depth raises ``TypeError``) and checked: it must fit
      ``MAX_EVIDENCE_BYTES`` and match the given size and fingerprint, or
      ``EvidenceIntegrityError`` is raised;
    * the supported serializers, ``canonical_json`` and ``to_json``, re-check
      before producing any text, so even a change that gets around the
      read-only containers (for example ``dict.__setitem__(...)``) cannot be
      serialized. Being integrity-checked does NOT make a text safe to send:
      see the contract below.

    Serialization contract (pinned by ``tests/test_ai_serialization_contract.py``):

    * PROVIDER-BOUND TEXT: ``canonical_json()`` is the ONLY sanctioned
      provider-bound serialized text. Its exact bytes (ASCII, so its UTF-8 and
      ASCII forms are the same bytes) are what ``fingerprint`` hashes and
      ``size_bytes`` counts, and the ``MAX_EVIDENCE_BYTES`` (32,768-byte) cap
      applies to exactly those bytes.
    * NOT PROVIDER-BOUND: ``to_json()`` is a convenience/debug rendering. It is
      integrity-checked first, but its text is not what is hashed or measured,
      it can differ from the hashed text for unnormalized content, and its
      formatted output (notably ``indent=2``) is NOT guaranteed to stay within
      the cap: whitespace alone can push a valid packet over it. Never use it
      as provider payload text.
    * ALSO CHECKED: ``verify_integrity()`` and ``dataclasses.replace`` (which
      re-runs validation).
    * NOT VERIFIED: reading ``.content`` directly, ``dataclasses.asdict`` /
      ``astuple``, ``vars``, ``repr``, ``copy``, ``pickle`` and the module-level
      ``fingerprint.canonical_json(content)``. ``content`` stays a public
      attribute, so a tampered packet can still be read, and serialized by
      hand, through these. A consumer must not use them to produce what is
      sent. No such consumer exists yet.

    To change evidence, build a new packet from the analysis."""

    content: dict[str, Any]
    fingerprint: str
    size_bytes: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "content", _freeze(self.content))
        self.verify_integrity()

    def verify_integrity(self) -> None:
        """Raise ``EvidenceIntegrityError`` unless the content is valid JSON
        evidence within the size cap whose size and fingerprint match."""
        try:
            size = len(canonical_json(self.content).encode("utf-8"))
            actual = fingerprint_content(self.content)
        except (TypeError, ValueError) as error:
            raise EvidenceIntegrityError(f"Evidence content is not valid JSON: {error}") from error
        if size > MAX_EVIDENCE_BYTES:
            raise EvidenceIntegrityError(
                f"Evidence is {size} bytes, over the {MAX_EVIDENCE_BYTES}-byte limit."
            )
        if size != self.size_bytes:
            raise EvidenceIntegrityError(
                f"Evidence is {size} bytes but the packet records {self.size_bytes}."
            )
        if actual != self.fingerprint:
            raise EvidenceIntegrityError("Evidence no longer matches its saved fingerprint.")

    def canonical_json(self) -> str:
        """The ONLY sanctioned provider-bound text. Integrity-checked first.

        These exact bytes are what ``fingerprint`` hashes and ``size_bytes``
        counts, and the 32,768-byte cap applies to them."""
        self.verify_integrity()
        return canonical_json(self.content)

    def to_json(self, *, indent: int | None = None) -> str:
        """Convenience/debug rendering ONLY; NOT provider-bound payload text.

        Integrity-checked first, but this text is not what is hashed or
        measured, and its formatted output (notably ``indent=2``) is NOT
        guaranteed to stay within the 32,768-byte cap. Send ``canonical_json()``
        instead."""
        self.verify_integrity()
        return json.dumps(self.content, ensure_ascii=False, indent=indent, sort_keys=True)


class EvidenceBuild:
    """APPLICATION-LOCAL build result: the provider-facing ``packet`` plus the
    ``aliases`` mapping (real column names behind the aliases).

    Only ``packet`` may be sent anywhere. This wrapper refuses to be pickled
    or copied into a plain structure by accident: it is not a dataclass (so
    ``dataclasses.asdict`` rejects it), it has no ``__dict__`` and its repr
    shows no names. A provider call must take ``build.packet`` (and send its
    ``canonical_json()``, never ``to_json()``), never ``build``."""

    __slots__ = ("_aliases", "_packet")

    def __init__(self, packet: EvidencePacket, aliases: ColumnAliasMap) -> None:
        self._packet = packet
        self._aliases = aliases

    @property
    def packet(self) -> EvidencePacket:
        return self._packet

    @property
    def aliases(self) -> ColumnAliasMap:
        """LOCAL ONLY. Never send, store with the packet, or log."""
        return self._aliases

    def __repr__(self) -> str:
        return f"<EvidenceBuild: fingerprint={self._packet.fingerprint}, local only>"

    __str__ = __repr__

    def __reduce__(self) -> str | tuple[object, ...]:
        raise TypeError("EvidenceBuild is local-only; send build.packet, never the build.")

    def __copy__(self) -> EvidenceBuild:
        return self

    def __deepcopy__(self, memo: dict[int, object]) -> EvidenceBuild:
        return self


# --- text and number hygiene -------------------------------------------


def clean_text(value: object, max_chars: int) -> str:
    """Final scrub applied to EVERY string in the packet (defence in depth):
    NFC; invisible/format characters removed; control characters and all
    line/space variants collapsed to single spaces; length-limited. This is
    hygiene only - it is not what keeps names out (aliases do that)."""
    text = normalize_text(str(value))
    text = "".join(
        " " if unicodedata.category(ch)[0] in {"C", "Z"} else ch
        for ch in text
        if unicodedata.category(ch) != "Cf"
    )
    text = " ".join(text.split())
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text


def _choice(value: object, allowed: frozenset[str], default: str | None = None) -> str | None:
    """``value`` only if it is a member of the closed vocabulary ``allowed``;
    otherwise ``default`` (None means: leave the field out). Membership, not
    shape: an unknown value is never passed through."""
    if isinstance(value, str) and value in allowed:
        return value
    return default


def _num(value: object) -> float | int | None:
    """Numbers only; anything else (including bool) becomes None."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return value


def _take[T](items: list[T], limit: int, section: str, omitted: list[dict[str, Any]]) -> list[T]:
    if len(items) > limit:
        omitted.append({"section": section, "shown": limit, "total": len(items)})
    return items[:limit]


def _drop_empty(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v is not None}


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return clean_text(value, MAX_TEXT_CHARS)
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


# --- aliases -------------------------------------------------------------


def _notes_of(analysis: AnalysisPublic) -> list[dict[str, Any]]:
    assert analysis.profile is not None
    raw = (analysis.profile.model_extra or {}).get("import_notes") or []
    return [n for n in raw if isinstance(n, dict)]


def _collect_original_names(analysis: AnalysisPublic) -> list[str]:
    """Every column name any section may mention, in one fixed order: the
    profile's columns by position first (so aliases follow dataset order and
    do not depend on what other sections contain), then any name the profile
    lacks, in order of first mention. Collected from the UNCAPPED sources, so
    an alias never changes between size tiers."""
    profile = analysis.profile
    assert profile is not None
    names = [str(c.get("name", "")) for c in profile.columns]
    seen = set(names)

    def add(name: object) -> None:
        text = str(name)
        if text not in seen:
            seen.add(text)
            names.append(text)

    if analysis.statistics is not None:
        for item in analysis.statistics.columns:
            add(item.column)
        for skipped in analysis.statistics.skipped_columns:
            add(skipped)
    if analysis.cleaning is not None:
        for action in analysis.cleaning.column_actions:
            add(action.column)
    if analysis.correlations is not None:
        for pair in analysis.correlations.pairs:
            add(pair.column_a)
            add(pair.column_b)
    if analysis.outliers is not None:
        for outlier in analysis.outliers.columns:
            add(outlier.column)
    regression = analysis.regression
    if regression is not None and regression.model is not None:
        add(regression.model.target)
        for predictor in regression.model.predictors:
            add(predictor)
        for coefficient in regression.coefficients:
            if coefficient.name != "const":
                add(coefficient.name)
    charts = analysis.visualizations.charts if analysis.visualizations is not None else []
    for chart in charts:
        for column in (chart.x_column, chart.y_column, chart.group_column):
            if column:
                add(column)
    for note in _notes_of(analysis):
        columns = note.get("columns")
        for column in columns if isinstance(columns, list) else []:
            add(column)
        renamed = (note.get("details") or {}).get("renamed_from")
        if isinstance(renamed, dict):
            for new, base in renamed.items():
                add(new)
                add(base)
    return names


@dataclass(frozen=True)
class _Ctx:
    aliases: ColumnAliasMap
    caps: _Caps
    omitted: list[dict[str, Any]]

    def a(self, name: object) -> str:
        """Alias for a reference BY NAME. If several columns share that exact
        name the reference cannot say which one was meant, so no alias is
        guessed: ``AMBIGUOUS_ALIAS`` is written instead."""
        text = str(name)
        try:
            if self.aliases.is_duplicated(text):
                return AMBIGUOUS_ALIAS
            return self.aliases.alias_for(text)
        except KeyError:
            return UNMAPPED_ALIAS


# --- sections ----------------------------------------------------------


def _dataset_section(analysis: AnalysisPublic) -> dict[str, Any]:
    profile = analysis.profile
    assert profile is not None  # guaranteed by eligibility
    return {
        "rows_uploaded": profile.row_count,
        "columns_uploaded": profile.column_count,
        "numeric_columns": profile.numeric_column_count,
        "categorical_columns": profile.categorical_column_count,
        "date_columns": profile.date_column_count,
        "missing_cells_uploaded": profile.total_missing_values,
        "duplicate_rows_uploaded": profile.duplicate_row_count,
    }


def _column_entry(slot: int, column: dict[str, Any], ctx: _Ctx) -> dict[str, Any]:
    # By position (`slot`), so even two columns with the same exact name keep
    # distinct aliases.
    entry: dict[str, Any] = {
        "column": ctx.aliases.alias_for_slot(slot),
        "type": _choice(column.get("classification"), COLUMN_CLASSIFICATION_VALUES, UNKNOWN_VALUE),
        "missing_count": _num(column.get("missing_count")),
        "missing_percent": _num(column.get("missing_percentage")),
        "unique_count": _num(column.get("unique_count")),
        # `min_value` / `max_value` are real cells of the dataset: not copied.
    }
    # Flags appear only when set. Their *examples* are raw cell values and
    # are never copied.
    if column.get("likely_identifier"):
        entry["likely_identifier"] = True
    number_format = _choice(column.get("number_format"), NUMBER_FORMAT_VALUES)
    if number_format:
        entry["number_format"] = number_format
    if column.get("date_order_issue"):
        entry["date_order_issue"] = True
    return _drop_empty(entry)


def _columns_section(analysis: AnalysisPublic, ctx: _Ctx) -> list[dict[str, Any]]:
    assert analysis.profile is not None
    columns = [_column_entry(i, c, ctx) for i, c in enumerate(analysis.profile.columns)]
    return _take(columns, ctx.caps.columns, "columns", ctx.omitted)


# Import-note text is NEVER copied: the original messages quote column names,
# sheet names and example cell values. Each known note code is re-stated from
# a fixed template that uses aliases and counts only. An unknown (e.g. future)
# code is NOT passed through: it is reported as the safe constant "unknown"
# (closed vocabulary), keeps its severity (also closed) and aliased columns,
# and gets no message.
_NA_MISSING = (
    "The text 'NA' was read as a missing value in the listed columns{count}, because "
    "every other value in those columns is a number."
)
_NA_KEPT = (
    "The text 'NA' was kept as a real value, not as missing, in the listed columns{count}, "
    "because those columns hold text."
)
_BLANK_HEADERS = "{n} column(s) had no header and were named automatically."
_DUPLICATE_HEADERS = (
    "The listed columns share a header with another column and look like they were "
    "renamed automatically."
)
_IDENTIFIERS = (
    "The listed columns look like identifiers (row numbers or values that are almost all "
    "different). They are still included in the analysis, so correlations, outliers and "
    "regression involving them will not be meaningful."
)
_FORMATTED_NUMBERS = (
    "The listed columns hold numbers written as text (currency, percent or "
    "thousands-separated). They were treated as categories, not numbers, so no "
    "statistics or regression were computed for them."
)
_AMBIGUOUS_DATES = (
    "The listed date columns are written in an order that cannot be told apart "
    "(day/month or month/day), so dates may be read in the wrong order. Dates are not converted."
)
_EXTRA_SHEETS = (
    "The workbook has more than one sheet. Only the first sheet was analysed; "
    "the others were ignored."
)


def _count_text(details: dict[str, Any]) -> str:
    cells = details.get("cells_by_column")
    if isinstance(cells, dict):
        counts = [v for v in cells.values() if isinstance(v, int) and not isinstance(v, bool)]
        if counts:
            total = sum(counts)
            return f" ({total:,} cell{'s' if total != 1 else ''})"
    return ""


def _note_entry(note: dict[str, Any], ctx: _Ctx) -> dict[str, Any]:
    code = _choice(note.get("code"), IMPORT_NOTE_CODE_VALUES, UNKNOWN_VALUE) or UNKNOWN_VALUE
    raw_columns = note.get("columns")
    names = [str(n) for n in raw_columns] if isinstance(raw_columns, list) else []
    aliases = [ctx.a(n) for n in names]
    limit = ctx.caps.note_columns
    entry: dict[str, Any] = {
        "code": code,
        "severity": _choice(note.get("severity"), IMPORT_NOTE_SEVERITY_VALUES, UNKNOWN_VALUE),
        "columns": aliases[:limit],
    }
    if len(aliases) > limit:
        entry["columns_total"] = len(aliases)
    raw_details = note.get("details")
    details: dict[str, Any] = raw_details if isinstance(raw_details, dict) else {}

    if code == "na_text_read_as_missing":
        entry["message"] = _NA_MISSING.format(count=_count_text(details))
    elif code == "na_text_kept_as_value":
        entry["message"] = _NA_KEPT.format(count=_count_text(details))
    elif code == "blank_headers":
        entry["message"] = _BLANK_HEADERS.format(n=len(names))
    elif code == "duplicate_headers":
        entry["message"] = _DUPLICATE_HEADERS
        renamed = details.get("renamed_from")
        if isinstance(renamed, dict):
            pairs = list(renamed.items())[:limit]
            entry["renamed_from"] = {ctx.a(new): ctx.a(base) for new, base in pairs}
    elif code == "likely_identifier_columns":
        entry["message"] = _IDENTIFIERS
    elif code == "formatted_numbers_as_text":
        entry["message"] = _FORMATTED_NUMBERS
        formats = details.get("formats")
        if isinstance(formats, dict):
            kinds = {
                ctx.a(column): _choice(info.get("kind"), NUMBER_FORMAT_VALUES, UNKNOWN_VALUE)
                for column, info in list(formats.items())[:limit]
                if isinstance(info, dict)
            }
            if kinds:
                entry["format_kinds"] = kinds
    elif code == "ambiguous_dates":
        entry["message"] = _AMBIGUOUS_DATES
        issues = details.get("issues")
        if isinstance(issues, dict):
            entry["date_issue_kinds"] = {
                ctx.a(column): _choice(kind, DATE_ISSUE_VALUES, UNKNOWN_VALUE)
                for column, kind in list(issues.items())[:limit]
            }
    elif code == "xlsx_extra_sheets":
        entry["message"] = _EXTRA_SHEETS
        ignored = details.get("ignored_sheets")
        if isinstance(ignored, list):
            # Upstream lists at most a few names, so this can understate.
            entry["ignored_sheet_count_listed"] = len(ignored)
    return entry


def _notes_section(analysis: AnalysisPublic, ctx: _Ctx) -> list[dict[str, Any]]:
    notes = [_note_entry(n, ctx) for n in _notes_of(analysis)]
    return _take(notes, ctx.caps.notes, "import_notes", ctx.omitted)


_CLEANING_SETTINGS: dict[str, frozenset[str]] = {
    "numeric_strategy": frozenset({"median", "unchanged"}),
    "categorical_strategy": frozenset({"mode", "unchanged"}),
    "duplicate_strategy": frozenset({"remove", "keep"}),
}


def _cleaning_section(analysis: AnalysisPublic, ctx: _Ctx) -> dict[str, Any] | None:
    report = analysis.cleaning
    if report is None:
        return None
    actions: list[dict[str, Any]] = []
    for action in report.column_actions:
        actions.append(
            _drop_empty(
                {
                    "column": ctx.a(action.column),
                    "action": _choice(action.action, CLEANING_ACTION_VALUES, UNKNOWN_VALUE),
                    "method": _choice(action.method, CLEANING_METHOD_VALUES),
                    "reason": _choice(action.reason, CLEANING_REASON_VALUES),
                    # A numeric fill (a median) is a summary. A text fill is
                    # a real cell value (the most common category): omitted.
                    "fill_value": _num(action.fill_value),
                    "missing_before": action.missing_before,
                    "missing_after": action.missing_after,
                    "values_changed": action.values_changed,
                }
            )
        )
    settings = {
        key: value
        for key, value in report.config.items()
        if key in _CLEANING_SETTINGS and isinstance(value, str) and value in _CLEANING_SETTINGS[key]
    }
    return {
        "settings": settings,
        "rows_before": report.rows_before,
        "rows_after": report.rows_after,
        "rows_removed": report.rows_removed,
        "missing_before": report.missing_before,
        "missing_after": report.missing_after,
        "missing_values_imputed": report.missing_values_imputed,
        "duplicates_before": report.duplicates_before,
        "duplicates_after": report.duplicates_after,
        "duplicates_removed": report.duplicates_removed,
        "column_actions": _take(
            actions, ctx.caps.cleaning_actions, "cleaning_actions", ctx.omitted
        ),
    }


def _statistics_section(analysis: AnalysisPublic, ctx: _Ctx) -> dict[str, Any]:
    stats = analysis.statistics
    assert stats is not None  # guaranteed by eligibility
    rows = [
        _drop_empty(
            {
                **item.model_dump(exclude=set(WITHHELD_STATISTICS_FIELDS)),
                "column": ctx.a(item.column),
            }
        )
        for item in stats.columns
    ]
    skipped = [ctx.a(n) for n in stats.skipped_columns]
    return {
        "numeric_column_count": stats.numeric_column_count,
        "columns": _take(rows, ctx.caps.statistics, "statistics", ctx.omitted),
        "skipped_columns": _take(skipped, ctx.caps.skipped_names, "skipped_columns", ctx.omitted),
    }


def _correlations_section(analysis: AnalysisPublic, ctx: _Ctx) -> dict[str, Any] | None:
    result = analysis.correlations
    if result is None or not result.available:
        return None
    # Ranked by strength, ties broken by the aliases (dataset order), so the
    # order never depends on the real names.
    ranked = sorted(
        result.pairs,
        key=lambda p: (-abs(p.correlation), ctx.a(p.column_a), ctx.a(p.column_b)),
    )
    pairs = [
        {
            "column_a": ctx.a(p.column_a),
            "column_b": ctx.a(p.column_b),
            "correlation": p.correlation,
            "strength": _choice(p.strength, CORRELATION_STRENGTH_VALUES, UNKNOWN_VALUE),
            "direction": _choice(p.direction, CORRELATION_DIRECTION_VALUES, UNKNOWN_VALUE),
        }
        for p in ranked
    ]
    # The full matrix is not copied: it is n x n and every cell is derivable
    # from the pairs. Only the strongest pairs are kept.
    return {
        "numeric_column_count": result.numeric_column_count,
        "undefined_pair_count": result.undefined_pair_count,
        "pairs": _take(pairs, ctx.caps.correlation_pairs, "correlation_pairs", ctx.omitted),
    }


def _outliers_section(analysis: AnalysisPublic, ctx: _Ctx) -> dict[str, Any] | None:
    result = analysis.outliers
    if result is None:
        return None
    flagged = sorted(
        (c for c in result.columns if c.outlier_count > 0),
        key=lambda c: (-c.outlier_count, ctx.a(c.column)),
    )
    rows = [
        _drop_empty(
            {
                "column": ctx.a(c.column),
                "observation_count": c.observation_count,
                "outlier_count": c.outlier_count,
                "outlier_percentage": c.outlier_percentage,
                "lower_bound": c.lower_bound,
                "upper_bound": c.upper_bound,
            }
        )
        for c in flagged
    ]
    # Row positions (`outlier_indices`) are never copied.
    return {
        "method": _choice(result.method, OUTLIER_METHOD_VALUES, UNKNOWN_VALUE),
        "iqr_multiplier": result.iqr_multiplier,
        "columns_checked": len(result.columns),
        "columns_with_outliers": result.columns_with_outliers,
        "total_outlier_count": result.total_outlier_count,
        "columns": _take(rows, ctx.caps.outlier_columns, "outlier_columns", ctx.omitted),
    }


def _regression_section(analysis: AnalysisPublic, ctx: _Ctx) -> dict[str, Any] | None:
    result = analysis.regression
    if result is None or not result.available or result.model is None:
        return None
    model = result.model
    coefficients = [
        _drop_empty(
            {
                **c.model_dump(),
                # The model's constant term is named "const" by the engine.
                "name": "intercept" if c.name == "const" else ctx.a(c.name),
            }
        )
        for c in result.coefficients
    ]
    predictors = [ctx.a(p) for p in model.predictors]
    # `sample_predictions` (actual vs predicted for individual rows) is never
    # copied; `residual_summary` is aggregate and is.
    return {
        "target": ctx.a(model.target),
        "predictors": _take(predictors, ctx.caps.predictors, "regression_predictors", ctx.omitted),
        "predictor_count": len(model.predictors),
        "method": _choice(model.method, REGRESSION_METHOD_VALUES, UNKNOWN_VALUE),
        "observations_total": model.observations_total,
        "observations_used": model.observations_used,
        "rows_dropped_for_missing_values": model.rows_dropped_for_missing_values,
        "train_observations": model.train_observations,
        "test_observations": model.test_observations,
        "intercept": model.intercept,
        "metrics": result.metrics.model_dump() if result.metrics else None,
        "coefficients": _take(coefficients, ctx.caps.coefficients, "coefficients", ctx.omitted),
        "residual_summary": {
            key: value
            for key, value in result.residual_summary.items()
            if key in RESIDUAL_SUMMARY_KEYS
        },
    }


def _chart_title(chart_type: str, x: str | None, y: str | None, group: str | None) -> str:
    """Chart titles are never copied (they embed column names). Rebuilt from
    the chart type and aliases."""
    label = chart_type.replace("_", " ").replace("-", " ")
    if x and y:
        title = f"{label}: {y} vs {x}"
    elif y or x:
        title = f"{label}: {y or x}"
    else:
        title = label
    return f"{title} by {group}" if group and group not in (x, y) else title


def _charts_section(analysis: AnalysisPublic, ctx: _Ctx) -> list[dict[str, Any]] | None:
    result = analysis.visualizations
    if result is None or not result.available or not result.charts:
        return None
    charts: list[dict[str, Any]] = []
    for c in result.charts:
        chart_type = _choice(c.chart_type, CHART_TYPE_VALUES, UNKNOWN_VALUE) or UNKNOWN_VALUE
        x = ctx.a(c.x_column) if c.x_column else None
        y = ctx.a(c.y_column) if c.y_column else None
        group = ctx.a(c.group_column) if c.group_column else None
        charts.append(
            _drop_empty(
                {
                    "chart_type": chart_type,
                    "title": _chart_title(chart_type, x, y, group),
                    "x_column": x,
                    "y_column": y,
                    "group_column": group,
                }
            )
        )
    # Chart point data is never copied. At the smallest tier charts go.
    if ctx.caps.charts == 0:
        ctx.omitted.append({"section": "charts", "shown": 0, "total": len(charts)})
        return None
    return _take(charts, ctx.caps.charts, "charts", ctx.omitted)


def _coverage(
    analysis: AnalysisPublic, content: dict[str, Any], omitted: list[dict[str, Any]]
) -> dict[str, str]:
    """Plain statement of which analysis sections the AI can rely on."""
    removed_for_size = {o["section"] for o in omitted if o["shown"] == 0}

    def state(section: str, ran: bool) -> str:
        if content.get(section) is not None:
            return "included"
        if section in removed_for_size:
            return "omitted_for_size"
        return "not_available" if ran else "not_run"

    stage = analysis.stages
    return {
        "statistics": "included",
        "correlations": state("correlations", stage.get("correlations") == "completed"),
        "outliers": state("outliers", stage.get("outliers") == "completed"),
        "regression": state("regression", stage.get("regression") == "completed"),
        "charts": state("charts", stage.get("visualizations") == "completed"),
    }


def _warnings_section(
    analysis: AnalysisPublic, verdict: EligibilityResult, aliases: ColumnAliasMap
) -> list[dict[str, Any]]:
    """Machine-readable cautions from the eligibility rules. A warning flags a
    limit; it never certifies reliability."""
    basis = analysis.cleaned_profile or analysis.profile
    assert basis is not None
    warnings: list[dict[str, Any]] = []
    if SMALL_SAMPLE in verdict.warnings:
        warnings.append(
            {
                "code": SMALL_SAMPLE,
                "rows_after_cleaning": basis.row_count,
                "threshold_rows": SMALL_SAMPLE_ROWS,
            }
        )
    # Upstream sections refer to columns by name only. When several columns
    # share one exact name those references cannot say which column is meant,
    # so they are written as AMBIGUOUS_ALIAS and the AI is told. The aliases
    # listed are the positional ones from the column list (they carry no name).
    groups = aliases.duplicated_groups()
    if groups:
        warnings.append(
            {
                "code": DUPLICATE_COLUMN_NAMES,
                "ambiguous_reference": AMBIGUOUS_ALIAS,
                "column_groups": groups[:10],
                "group_count": len(groups),
            }
        )
    return warnings


# --- assembly ----------------------------------------------------------


def _assemble(
    analysis: AnalysisPublic,
    verdict: EligibilityResult,
    aliases: ColumnAliasMap,
    caps: _Caps,
) -> dict[str, Any]:
    ctx = _Ctx(aliases=aliases, caps=caps, omitted=[])
    content: dict[str, Any] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "dataset": _dataset_section(analysis),
        "warnings": _warnings_section(analysis, verdict, aliases),
        "columns": _columns_section(analysis, ctx),
        "import_notes": _notes_section(analysis, ctx),
        "cleaning": _cleaning_section(analysis, ctx),
        "statistics": _statistics_section(analysis, ctx),
        "correlations": _correlations_section(analysis, ctx),
        "outliers": _outliers_section(analysis, ctx),
        "regression": _regression_section(analysis, ctx),
        "charts": _charts_section(analysis, ctx),
    }
    content["coverage"] = _coverage(analysis, content, ctx.omitted)
    content["omitted"] = ctx.omitted
    # Absent sections are removed (coverage already says why), every string is
    # scrubbed, then the whole thing is passed through the canonical form so
    # `content` is exactly the text that is measured and hashed.
    content = {k: v for k, v in content.items() if v is not None}
    normalized: dict[str, Any] = json.loads(canonical_json(_scrub(content)))
    return normalized


def build_evidence(analysis: AnalysisPublic) -> EvidenceBuild:
    """Build the evidence, or raise ``EvidenceNotEligible``.

    Returns an ``EvidenceBuild``: the provider-facing ``.packet`` (content,
    fingerprint, size) and the application-local ``.aliases`` mapping, kept
    apart on purpose. Pure and deterministic: the same analysis always gives
    the same packet and the same fingerprint. No database, no network, no AI.
    """
    verdict = check_eligibility(analysis)
    if not verdict.eligible:
        raise EvidenceNotEligible(verdict)

    aliases = ColumnAliasMap(_collect_original_names(analysis))
    for caps in _TIERS:
        content = _assemble(analysis, verdict, aliases, caps)
        size = len(canonical_json(content).encode("utf-8"))
        if size <= MAX_EVIDENCE_BYTES:
            packet = EvidencePacket(
                content=content,
                fingerprint=fingerprint_content(content),
                size_bytes=size,
            )
            return EvidenceBuild(packet, aliases)

    raise EvidenceNotEligible(
        EligibilityResult(
            eligible=False,
            reason_code=EVIDENCE_TOO_LARGE,
            message=(
                "The results for this dataset are too large to summarise safely "
                "(for example, a very large number of columns)."
            ),
        )
    )


def build_evidence_packet(analysis: AnalysisPublic) -> EvidencePacket:
    """The provider-facing packet only (no alias mapping). Code that must turn
    an alias back into a column name uses ``build_evidence`` instead."""
    return build_evidence(analysis).packet
