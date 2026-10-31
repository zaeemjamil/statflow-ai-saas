"""
Dataset profiling - generalizes StatFlow's app.py /analyze endpoint
(Phase 1 audit §6) to any uploaded schema. Implemented in Phase 6 (the
Phase 3 stub guessed Phase 7; upload/profiling turned out to be its own
phase). Inspection only - never mutates the DataFrame it's given, and
never imputes/dedupes/deletes (that's Phase 7's cleaning step, on the
user's explicit, transparent choice - not something profiling decides
on its own).
"""

from __future__ import annotations

import re
from typing import Any, Literal

import pandas as pd

from app.analytics import data_quality
from app.analytics.data_quality import ImportNote

ColumnClassification = Literal["numeric", "categorical", "date"]

# A date-parse attempt is only made for values that already look
# date-shaped (contain a separator, or a 3+ letter run like a month
# name) - otherwise a column of plain digit-string IDs (e.g. an 8-digit
# order/record number formatted like a date, "20260115") gets a
# deceptively high pd.to_datetime "success" rate and is misclassified
# as a date column. Verified directly: a column of unbroken 8-digit
# numeric-looking strings (no separators) parsed as dates 100% of the
# time under to_datetime(errors="coerce", format="mixed") alone -
# comfortably past the 90% threshold below, with nothing else to catch
# it. The one real trade-off this accepts: a genuine date column stored
# as separator-less digits (e.g. literal "20260115" meaning a date, not
# an ID) is classified as categorical instead of date, since nothing
# short of a column-name heuristic could tell the two apart - a
# deliberate call given the instruction to avoid aggressively
# converting text columns, not an oversight.
#
# Dot-separated numeric dates ("01.02.2025", "25.12.25") are recognised by
# their full d.m.y shape, not by a bare "."; a lone dot would also match
# decimals and codes such as "1.5" or "v2.3". The shape mirrors
# data_quality._NUMERIC_DATE_RE (1-2 digit day/month, 2- or 4-digit year).
_DATE_LIKE_PATTERN = re.compile(
    r"[-/:]|[A-Za-z]{3,}|(?<![\d.])\d{1,2}\.\d{1,2}\.(?:\d{4}|\d{2})(?![\d.])"
)
_DATE_LIKE_SAMPLE_MIN_FRACTION = 0.5
_DATE_PARSE_SUCCESS_MIN_FRACTION = 0.9
_DATE_DETECTION_SAMPLE_SIZE = 200


def _looks_date_like(sample: pd.Series) -> bool:
    if sample.empty:
        return False
    matches = sample.astype(str).str.contains(_DATE_LIKE_PATTERN, regex=True)
    return bool(matches.mean() >= _DATE_LIKE_SAMPLE_MIN_FRACTION)


def _classify_column(series: pd.Series) -> ColumnClassification:
    # Booleans satisfy is_numeric_dtype in pandas but are semantically
    # closer to a 2-level categorical for analytics purposes (Phase 7's
    # regression/outlier logic shouldn't treat True/False as continuous).
    if pd.api.types.is_bool_dtype(series):
        return "categorical"
    # A column with no values at all (blank CSV cells are inferred as float64,
    # an empty XLSX column likewise) says nothing about its type, so it must
    # not be classified by dtype: it would count as a numeric analysis column
    # with no data. Zero-row frames keep their dtype-based classification.
    if len(series) > 0 and bool(series.isna().all()):
        return "categorical"
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "date"

    non_null = series.dropna()
    if non_null.empty:
        return "categorical"

    sample = non_null.sample(min(len(non_null), _DATE_DETECTION_SAMPLE_SIZE), random_state=0)
    if not _looks_date_like(sample):
        return "categorical"

    parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
    success_fraction = parsed.notna().mean()
    return "date" if success_fraction >= _DATE_PARSE_SUCCESS_MIN_FRACTION else "categorical"


def _profile_column(
    name: str, series: pd.Series, row_count: int, *, inspect_data_quality: bool = False
) -> dict[str, Any]:
    missing_count = int(series.isna().sum())
    unique_count = int(series.nunique(dropna=True))
    classification = _classify_column(series)

    # Numeric columns carry min/max beyond the generic fields every
    # column gets — enough for the frontend to do something useful
    # (e.g. sanity-check ranges, seed a regression variable picker)
    # without precomputing mean/median/std/quartiles, which is Phase 7's
    # descriptive-statistics job, not profiling's.
    min_value: float | None = None
    max_value: float | None = None
    if classification == "numeric":
        non_null = series.dropna()
        if not non_null.empty:
            min_value = float(non_null.min())
            max_value = float(non_null.max())

    column: dict[str, Any] = {
        "name": name,
        "classification": classification,
        "pandas_dtype": str(series.dtype),
        "missing_count": missing_count,
        "missing_percentage": round(missing_count / row_count * 100, 2) if row_count else 0.0,
        "unique_count": unique_count,
        "is_unique": row_count > 0 and unique_count == row_count,
        "min_value": min_value,
        "max_value": max_value,
    }

    if inspect_data_quality:
        # Stage 3 findings. Detection only: nothing here changes the
        # classification or the data (see app/analytics/data_quality.py).
        number_format = data_quality.detect_number_format(series)
        # Text that is really formatted numbers ("$1,200") is a number, not an
        # identifier, even though every string is distinct.
        identifier = (
            None
            if number_format is not None
            else data_quality.detect_identifier(series, classification)
        )
        column["likely_identifier"] = identifier is not None
        column["identifier_reason"] = identifier
        column["number_format"] = number_format[0] if number_format else None
        column["number_format_examples"] = number_format[1] if number_format else []
        column["date_order_issue"] = (
            data_quality.detect_date_order_issue(series) if classification == "date" else None
        )
    return column


def profile_dataset(
    df: pd.DataFrame,
    *,
    inspect_data_quality: bool = False,
    import_notes: list[ImportNote] | None = None,
) -> dict[str, Any]:
    """
    Inspect a parsed dataset and classify its columns. Never mutates
    `df` - every pandas call here is read-only (dropna/sample/nunique
    all return copies or scalars, none mutate in place).

    Returns dataset-level counts plus a per-column profile - see
    app/schemas/upload.py's DatasetProfile/ColumnProfile for the exact
    shape this is serialized into.

    `inspect_data_quality=True` (used for a new upload only) adds the Stage 3
    per-column findings and a dataset-level `import_notes` list (the notes
    from reading the file plus the ones derived from the columns). Without
    it the output is exactly what it was before Stage 3, which is what the
    cleaned-data profile and old callers get.
    """
    row_count = len(df)
    columns = [
        _profile_column(
            str(col), df.iloc[:, position], row_count, inspect_data_quality=inspect_data_quality
        )
        for position, col in enumerate(df.columns)
    ]

    classification_counts = {"numeric": 0, "categorical": 0, "date": 0}
    for column in columns:
        classification_counts[column["classification"]] += 1

    profile: dict[str, Any] = {
        "row_count": row_count,
        "column_count": len(df.columns),
        "numeric_column_count": classification_counts["numeric"],
        "categorical_column_count": classification_counts["categorical"],
        "date_column_count": classification_counts["date"],
        "total_missing_values": int(df.isna().sum().sum()),
        "duplicate_row_count": int(df.duplicated().sum()),
        "columns": columns,
    }
    if inspect_data_quality:
        profile["import_notes"] = list(import_notes or []) + _column_notes(columns)
    return profile


def _column_notes(columns: list[dict[str, Any]]) -> list[ImportNote]:
    notes: list[ImportNote] = []

    by_reason: dict[str, list[str]] = {}
    for column in columns:
        if column.get("likely_identifier"):
            by_reason.setdefault(column["identifier_reason"], []).append(column["name"])
    identifier = data_quality.identifier_note(by_reason)
    if identifier is not None:
        notes.append(identifier)

    formats = {
        c["name"]: (c["number_format"], c["number_format_examples"])
        for c in columns
        if c.get("number_format")
    }
    formatted = data_quality.number_format_note(formats)
    if formatted is not None:
        notes.append(formatted)

    dates = {c["name"]: c["date_order_issue"] for c in columns if c.get("date_order_issue")}
    ambiguous = data_quality.date_order_note(dates)
    if ambiguous is not None:
        notes.append(ambiguous)
    return notes
