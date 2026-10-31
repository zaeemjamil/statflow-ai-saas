"""Phase 9 Stage 1 final correction: the packet holds only CLOSED vocabularies.

A string that merely *looks like* a system label proves nothing: a column named
``ZZ_TOKEN_COL_A`` is letters, digits and underscores, exactly like ``numeric``.
So every enum-like field is checked for MEMBERSHIP in an explicit set. These
tests inject distinctive token-shaped sentinels into every such metadata field
(and use token-shaped column names), then look for them in every supported
serialization of the packet, and check that every token-shaped string and every
key that does appear is a known constant.
"""

from __future__ import annotations

import dataclasses
import json
import re
from typing import Any

import pytest

from app.ai import evidence
from app.ai.evidence import (
    CHART_TYPE_VALUES,
    CLEANING_ACTION_VALUES,
    CLEANING_METHOD_VALUES,
    CLEANING_REASON_VALUES,
    COLUMN_CLASSIFICATION_VALUES,
    CORRELATION_DIRECTION_VALUES,
    CORRELATION_STRENGTH_VALUES,
    DATE_ISSUE_VALUES,
    IMPORT_NOTE_CODE_VALUES,
    IMPORT_NOTE_SEVERITY_VALUES,
    NUMBER_FORMAT_VALUES,
    OUTLIER_METHOD_VALUES,
    REGRESSION_METHOD_VALUES,
    RESIDUAL_SUMMARY_KEYS,
    UNKNOWN_VALUE,
    EvidenceBuild,
    EvidencePacket,
    _choice,
    build_evidence,
)
from app.ai.fingerprint import canonical_json
from app.schemas.analysis import (
    AnalysisPublic,
    ColumnStatistics,
    RegressionCoefficient,
    RegressionMetrics,
)
from tests.ai_helpers import make_analysis, sample_frame

TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]{1,40}")
ALIAS_RE = re.compile(r"Column_(\d{3,}|ambiguous|unmapped)")

# Distinctive, token-shaped (the OLD check would have accepted every one).
S_CLASS = "ZZ_TOKEN_SENTINEL_CLASS"
S_FORMAT = "ZZ_TOKEN_SENTINEL_FORMAT"
S_SEVERITY = "ZZ_TOKEN_SENTINEL_SEVERITY"
S_CODE = "ZZ_TOKEN_SENTINEL_CODE"
S_KIND = "ZZ_TOKEN_SENTINEL_KIND"
S_DATE = "ZZ_TOKEN_SENTINEL_DATE"
S_ACTION = "ZZ_TOKEN_SENTINEL_ACTION"
S_METHOD = "ZZ_TOKEN_SENTINEL_METHOD"
S_REASON = "ZZ_TOKEN_SENTINEL_REASON"
S_REGRESSION = "ZZ_TOKEN_SENTINEL_REGR"
S_OUTLIER = "ZZ_TOKEN_SENTINEL_OUTL"
S_CHART = "ZZ_TOKEN_SENTINEL_CHART"
S_STRENGTH = "ZZ_TOKEN_SENTINEL_STRENGTH"
S_DIRECTION = "ZZ_TOKEN_SENTINEL_DIRECTION"
S_RESIDUAL = "ZZ_TOKEN_SENTINEL_RESID"
S_SETTING_KEY = "ZZ_TOKEN_SENTINEL_SETKEY"
S_SETTING_VALUE = "ZZ_TOKEN_SENTINEL_SETVAL"
VALUE_SENTINELS = [
    S_CLASS,
    S_FORMAT,
    S_SEVERITY,
    S_CODE,
    S_KIND,
    S_DATE,
    S_ACTION,
    S_METHOD,
    S_REASON,
    S_REGRESSION,
    S_OUTLIER,
    S_CHART,
    S_STRENGTH,
    S_DIRECTION,
    S_RESIDUAL,
    S_SETTING_KEY,
    S_SETTING_VALUE,
]
COLUMN_RENAMES = {
    "when": "ZZ_TOKEN_COL_WHEN",
    "x": "ZZ_TOKEN_COL_X",
    "y": "ZZ_TOKEN_COL_Y",
    "z": "ZZ_TOKEN_COL_Z",
    "group": "ZZ_TOKEN_COL_GROUP",
}
NAME_SENTINELS = list(COLUMN_RENAMES.values())
ALL_SENTINELS = [*VALUE_SENTINELS, *NAME_SENTINELS, "ZZ_TOKEN"]


def _token_named_analysis() -> AnalysisPublic:
    frame = sample_frame().rename(columns=COLUMN_RENAMES)
    # Missing values, so the cleaning step really produces column actions (one
    # numeric median fill, one text mode fill) for the hostile-metadata tests.
    frame.loc[[2, 5], "ZZ_TOKEN_COL_Z"] = float("nan")
    frame.loc[7, "ZZ_TOKEN_COL_GROUP"] = None
    frame["ZZ_TOKEN_COL_GROUP"] = "ZZ_TOKEN_CELL_" + frame["ZZ_TOKEN_COL_GROUP"]
    return make_analysis(
        frame,
        parse_notes=True,
        extra_sheets=["Sheet1", "ZZ_TOKEN_SHEET"],
        regression=("ZZ_TOKEN_COL_Y", ["ZZ_TOKEN_COL_X", "ZZ_TOKEN_COL_Z"]),
    )


def _inject_hostile_metadata(analysis: AnalysisPublic) -> AnalysisPublic:
    """Overwrite every enum-like field with a token-shaped sentinel."""
    a = analysis.model_copy(deep=True)
    profile = a.profile
    assert profile is not None

    for i, column in enumerate(profile.columns):
        column["classification"] = f"{S_CLASS}_{i}"
        column["number_format"] = S_FORMAT

    notes = (profile.model_extra or {}).get("import_notes")
    assert isinstance(notes, list)
    for note in notes:
        note["severity"] = S_SEVERITY
        details = note.get("details")
        if isinstance(details, dict):
            for info in (details.get("formats") or {}).values():
                info["kind"] = S_KIND
            for column in list(details.get("issues") or {}):
                details["issues"][column] = S_DATE
    # Notes with hostile codes: one that is a known code with a hostile
    # severity, one entirely unknown, one with a non-list `columns`.
    notes.append(
        {
            "code": S_CODE,
            "severity": S_SEVERITY,
            "message": "ZZ_TOKEN_MESSAGE should never be copied",
            "columns": ["ZZ_TOKEN_COL_X"],
            "details": {"formats": {"ZZ_TOKEN_COL_X": {"kind": S_KIND}}},
        }
    )
    notes.append(
        {"code": "blank_headers", "severity": S_SEVERITY, "columns": S_CODE, "details": []}
    )

    assert a.cleaning is not None
    actions = [
        action.model_copy(update={"action": S_ACTION, "method": S_METHOD, "reason": S_REASON})
        for action in a.cleaning.column_actions
    ]
    a.cleaning = a.cleaning.model_copy(
        update={
            "column_actions": actions,
            "config": {
                **a.cleaning.config,
                "numeric_strategy": S_SETTING_VALUE,
                S_SETTING_KEY: S_SETTING_VALUE,
            },
        }
    )

    if a.correlations is not None:
        a.correlations = a.correlations.model_copy(
            update={
                "pairs": [
                    p.model_copy(update={"strength": S_STRENGTH, "direction": S_DIRECTION})
                    for p in a.correlations.pairs
                ]
            }
        )
    if a.outliers is not None:
        a.outliers = a.outliers.model_copy(update={"method": S_OUTLIER})
    if a.regression is not None and a.regression.model is not None:
        a.regression = a.regression.model_copy(
            update={
                "model": a.regression.model.model_copy(update={"method": S_REGRESSION}),
                "residual_summary": {**a.regression.residual_summary, S_RESIDUAL: 1.0},
            }
        )
    if a.visualizations is not None:
        a.visualizations = a.visualizations.model_copy(
            update={
                "charts": [
                    c.model_copy(update={"chart_type": S_CHART}) for c in a.visualizations.charts
                ]
            }
        )
    return a


def _hostile_build() -> EvidenceBuild:
    return build_evidence(_inject_hostile_metadata(_token_named_analysis()))


def _serializations(packet: EvidencePacket) -> list[str]:
    """Every supported provider-facing text form of the packet."""
    content = packet.content
    return [
        canonical_json(content),
        packet.canonical_json(),
        packet.to_json(),
        packet.to_json(indent=2),
        json.dumps(content),
        json.dumps(content, ensure_ascii=False),
        json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True),
        json.dumps(content, separators=(",", ":")),
        json.dumps(dataclasses.asdict(packet), ensure_ascii=False),
        json.dumps(dataclasses.asdict(packet), indent=4),
        repr(packet),
        str(packet),
        repr(content),
        str(content),
    ]


# --- the vocabulary check itself ----------------------------------------


def test_choice_accepts_only_members_never_token_shaped_strangers() -> None:
    allowed = frozenset({"numeric", "date"})
    assert _choice("numeric", allowed, UNKNOWN_VALUE) == "numeric"
    assert _choice("ZZ_TOKEN_COL_A", allowed, UNKNOWN_VALUE) == UNKNOWN_VALUE  # token-shaped
    assert _choice("ZZ_TOKEN_COL_A", allowed) is None  # omitted
    assert _choice("Numeric", allowed) is None  # not even case-folded
    assert _choice("numeric ", allowed) is None  # not stripped into shape
    for odd in (None, 3, 2.5, True, ["numeric"], {"numeric": 1}, ("date",), b"date"):
        assert _choice(odd, allowed, UNKNOWN_VALUE) == UNKNOWN_VALUE


def test_the_vocabularies_match_what_the_engine_can_produce() -> None:
    assert COLUMN_CLASSIFICATION_VALUES == {"numeric", "categorical", "date"}
    assert NUMBER_FORMAT_VALUES == {"currency", "percent", "thousands"}
    assert DATE_ISSUE_VALUES == {"ambiguous", "inconsistent", "partly_ambiguous"}
    assert IMPORT_NOTE_SEVERITY_VALUES == {"info", "warning"}
    assert CLEANING_ACTION_VALUES == {"imputed", "left_unchanged"}
    assert CLEANING_METHOD_VALUES == {"median", "mode"}
    assert CLEANING_REASON_VALUES == {"no_non_missing_values", "strategy_unchanged"}
    assert REGRESSION_METHOD_VALUES == {"ols"}
    assert OUTLIER_METHOD_VALUES == {"iqr"}
    assert CHART_TYPE_VALUES == {"scatter", "line", "bar", "histogram", "count"}
    assert CORRELATION_STRENGTH_VALUES == {"strong", "moderate", "weak", "negligible"}
    assert CORRELATION_DIRECTION_VALUES == {"positive", "negative"}
    assert RESIDUAL_SUMMARY_KEYS == {"mean", "std", "min", "max"}
    assert {
        "na_text_read_as_missing",
        "na_text_kept_as_value",
        "blank_headers",
        "duplicate_headers",
        "likely_identifier_columns",
        "formatted_numbers_as_text",
        "ambiguous_dates",
        "xlsx_extra_sheets",
    } == IMPORT_NOTE_CODE_VALUES


def test_every_real_value_the_engine_produces_is_in_its_vocabulary() -> None:
    """The allowlists must not silently throw away real output."""
    packet = build_evidence(_token_named_analysis()).packet
    content = packet.content
    assert {c["type"] for c in content["columns"]} <= COLUMN_CLASSIFICATION_VALUES
    assert UNKNOWN_VALUE not in {c["type"] for c in content["columns"]}
    assert {n["code"] for n in content["import_notes"]} <= IMPORT_NOTE_CODE_VALUES
    assert {n["severity"] for n in content["import_notes"]} <= IMPORT_NOTE_SEVERITY_VALUES
    assert content["regression"]["method"] == "ols"
    assert content["outliers"]["method"] == "iqr"
    assert {c["chart_type"] for c in content["charts"]} <= CHART_TYPE_VALUES
    assert UNKNOWN_VALUE not in {c["chart_type"] for c in content["charts"]}
    assert set(content["regression"]["residual_summary"]) == RESIDUAL_SUMMARY_KEYS
    for pair in content["correlations"]["pairs"]:
        assert pair["strength"] in CORRELATION_STRENGTH_VALUES
        assert pair["direction"] in CORRELATION_DIRECTION_VALUES


# --- hostile metadata never reaches the packet --------------------------


def test_the_sentinels_are_token_shaped_so_the_old_check_would_have_passed_them() -> None:
    for sentinel in [*VALUE_SENTINELS, *NAME_SENTINELS]:
        assert TOKEN_RE.fullmatch(sentinel), sentinel


def test_no_sentinel_appears_in_any_serialization_of_the_packet() -> None:
    build = _hostile_build()
    for form in _serializations(build.packet):
        for sentinel in ALL_SENTINELS:
            assert sentinel not in form, f"{sentinel!r} leaked"
        assert "ZZ_" not in form and "SENTINEL" not in form
        assert "ZZ_TOKEN_MESSAGE" not in form


def test_no_original_to_alias_mapping_appears_in_any_serialization() -> None:
    build = _hostile_build()
    mapping = {build.aliases.original_for(a): a for a in build.aliases.aliases()}
    assert set(NAME_SENTINELS) <= set(mapping)  # the mapping does know the names locally
    for form in _serializations(build.packet):
        for original, alias in mapping.items():
            assert original not in form
            # No fragment pairing a name with its alias, in either order.
            assert not re.search(re.escape(original) + r".{0,8}" + re.escape(alias), form)
            assert not re.search(re.escape(alias) + r".{0,8}" + re.escape(original), form)
        for forbidden in ("alias_map", "original_name", "originals", "mapping"):
            assert forbidden not in form


def test_unknown_values_become_safe_constants_or_are_omitted() -> None:
    content = _hostile_build().packet.content

    assert {c["type"] for c in content["columns"]} == {UNKNOWN_VALUE}
    assert all("number_format" not in c for c in content["columns"])

    for note in content["import_notes"]:
        assert note["severity"] == UNKNOWN_VALUE
    unknown_notes = [n for n in content["import_notes"] if n["code"] == UNKNOWN_VALUE]
    assert len(unknown_notes) == 1
    assert "message" not in unknown_notes[0]  # no message for an unrecognised code
    assert "format_kinds" not in unknown_notes[0]
    for note in content["import_notes"]:
        for kind_key in ("format_kinds", "date_issue_kinds"):
            assert set(note.get(kind_key, {}).values()) <= {UNKNOWN_VALUE}

    actions = content["cleaning"]["column_actions"]
    assert actions
    for action in actions:
        assert action["action"] == UNKNOWN_VALUE
        assert "method" not in action and "reason" not in action
    assert content["cleaning"]["settings"].get("numeric_strategy") is None
    assert S_SETTING_KEY not in content["cleaning"]["settings"]

    for pair in content["correlations"]["pairs"]:
        assert pair["strength"] == UNKNOWN_VALUE
        assert pair["direction"] == UNKNOWN_VALUE
    assert content["outliers"]["method"] == UNKNOWN_VALUE
    assert content["regression"]["method"] == UNKNOWN_VALUE
    assert set(content["regression"]["residual_summary"]) <= RESIDUAL_SUMMARY_KEYS
    for chart in content["charts"]:
        assert chart["chart_type"] == UNKNOWN_VALUE
        assert S_CHART not in chart["title"]


def test_hostile_values_do_not_change_aliases_or_break_the_size_cap() -> None:
    clean = build_evidence(_token_named_analysis())
    hostile = _hostile_build()
    assert clean.aliases.aliases() == hostile.aliases.aliases()
    assert hostile.packet.size_bytes <= evidence.MAX_EVIDENCE_BYTES
    assert hostile.packet.fingerprint != clean.packet.fingerprint  # values did change


# --- everything left in the packet is a known constant -------------------


FIXED_KEYS = {
    "schema_version", "dataset", "warnings", "columns", "import_notes", "cleaning",
    "statistics", "correlations", "outliers", "regression", "charts", "coverage",
    "omitted", "rows_uploaded", "columns_uploaded", "numeric_columns",
    "categorical_columns", "date_columns", "missing_cells_uploaded",
    "duplicate_rows_uploaded", "column", "type", "missing_count", "missing_percent",
    "unique_count", "min", "max", "likely_identifier", "number_format",
    "date_order_issue", "code", "severity", "columns_total", "message", "renamed_from",
    "format_kinds", "date_issue_kinds", "ignored_sheet_count_listed", "settings",
    "rows_before", "rows_after", "rows_removed", "missing_before", "missing_after",
    "missing_values_imputed", "duplicates_before", "duplicates_after",
    "duplicates_removed", "column_actions", "action", "method", "reason", "fill_value",
    "values_changed", "numeric_column_count", "skipped_columns", "undefined_pair_count",
    "pairs", "column_a", "column_b", "correlation", "strength", "direction",
    "iqr_multiplier", "columns_checked", "columns_with_outliers", "total_outlier_count",
    "observation_count", "outlier_count", "outlier_percentage", "lower_bound",
    "upper_bound", "target", "predictors", "predictor_count", "observations_total",
    "observations_used", "rows_dropped_for_missing_values", "train_observations",
    "test_observations", "intercept", "metrics", "coefficients", "residual_summary",
    "name", "chart_type", "title", "x_column", "y_column", "group_column", "section",
    "shown", "total", "rows_after_cleaning", "threshold_rows", "ambiguous_reference",
    "column_groups", "group_count", "numeric_strategy", "categorical_strategy",
    "duplicate_strategy",
}  # fmt: skip
KNOWN_KEYS = (
    FIXED_KEYS
    | set(ColumnStatistics.model_fields)
    | set(RegressionCoefficient.model_fields)
    | set(RegressionMetrics.model_fields)
    | RESIDUAL_SUMMARY_KEYS
)
KNOWN_TOKEN_VALUES = (
    COLUMN_CLASSIFICATION_VALUES
    | NUMBER_FORMAT_VALUES
    | DATE_ISSUE_VALUES
    | IMPORT_NOTE_SEVERITY_VALUES
    | IMPORT_NOTE_CODE_VALUES
    | CLEANING_ACTION_VALUES
    | CLEANING_METHOD_VALUES
    | CLEANING_REASON_VALUES
    | REGRESSION_METHOD_VALUES
    | OUTLIER_METHOD_VALUES
    | CHART_TYPE_VALUES
    | CORRELATION_STRENGTH_VALUES
    | CORRELATION_DIRECTION_VALUES
    | {UNKNOWN_VALUE, "intercept", "small_sample", evidence.DUPLICATE_COLUMN_NAMES}
    | {"included", "omitted_for_size", "not_available", "not_run"}  # coverage states
    | {"median", "unchanged", "mode", "remove", "keep"}  # cleaning settings
    | {
        "columns",
        "statistics",
        "skipped_columns",
        "correlation_pairs",
        "outlier_columns",
        "regression_predictors",
        "coefficients",
        "cleaning_actions",
        "import_notes",
        "charts",
    }  # fmt: skip  # `omitted` section names
)


def _keys_and_string_leaves(value: Any) -> tuple[set[str], set[str]]:
    keys: set[str] = set()
    leaves: set[str] = set()

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                keys.add(key)
                visit(item)
        elif isinstance(node, list):
            for item in node:
                visit(item)
        elif isinstance(node, str):
            leaves.add(node)

    visit(value)
    return keys, leaves


@pytest.mark.parametrize("hostile", [False, True])
def test_every_key_and_token_shaped_string_is_a_known_constant_or_an_alias(hostile: bool) -> None:
    analysis = _token_named_analysis()
    if hostile:
        analysis = _inject_hostile_metadata(analysis)
    content = build_evidence(analysis).packet.content
    keys, leaves = _keys_and_string_leaves(content)

    unknown_keys = {k for k in keys if k not in KNOWN_KEYS and not ALIAS_RE.fullmatch(k)}
    assert not unknown_keys, unknown_keys

    stray = {
        leaf
        for leaf in leaves
        if TOKEN_RE.fullmatch(leaf)
        and leaf not in KNOWN_TOKEN_VALUES
        and not ALIAS_RE.fullmatch(leaf)
    }
    assert not stray, stray


def test_free_text_in_the_packet_is_only_templates_and_aliases() -> None:
    content = _hostile_build().packet.content
    _, leaves = _keys_and_string_leaves(content)
    for leaf in leaves:
        if TOKEN_RE.fullmatch(leaf):
            continue
        # Messages and chart titles: after removing aliases, no sentinel remains.
        stripped = re.sub(r"Column_(?:\d{3,}|ambiguous|unmapped)", "", leaf)
        assert "ZZ_" not in stripped and "TOKEN" not in stripped


def test_original_column_names_are_never_dictionary_keys_either() -> None:
    build = _hostile_build()
    keys, _ = _keys_and_string_leaves(build.packet.content)
    assert not keys & set(NAME_SENTINELS)
    assert not any("ZZ_" in key for key in keys)
