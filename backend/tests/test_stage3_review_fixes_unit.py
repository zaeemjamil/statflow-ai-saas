"""Stage 3 review fixes - unit regression tests (no DB, no HTTP):

1. a column with no values at all is not a numeric analysis column;
2. dot-separated numeric dates are date-like (and flagged when ambiguous);
3. files uploaded before Stage 3 are re-read with the policy they were
   profiled under.
"""

from __future__ import annotations

import io
from typing import Any

import pandas as pd
import pytest

from app.analytics.descriptive import compute_descriptive_stats
from app.analytics.profiling import _classify_column, profile_dataset
from app.models import FileType
from app.services.file_service import (
    UploadLimits,
    is_legacy_upload,
    parse_dataset,
    parse_dataset_with_notes,
)


def _xlsx(frame: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="Sheet1", index=False)
    return buf.getvalue()


def _column(profile: dict[str, Any], name: str) -> dict[str, Any]:
    return next(c for c in profile["columns"] if c["name"] == name)


def _codes(profile: dict[str, Any]) -> list[str]:
    return [n["code"] for n in profile["import_notes"]]


# --- 1. entirely missing columns -------------------------------------------

_BLANK_CSV = b"a,empty,b\n1,,x\n2,,y\n3,,x\n4,,y\n"


def _all_missing_checks(df: pd.DataFrame) -> None:
    profile = profile_dataset(df, inspect_data_quality=True)
    empty = _column(profile, "empty")
    assert empty["classification"] == "categorical"
    assert empty["missing_count"] == len(df)
    assert empty["missing_percentage"] == 100.0
    assert empty["unique_count"] == 0
    assert empty["min_value"] is None and empty["max_value"] is None
    assert not empty["likely_identifier"]
    # Not counted as a numeric analysis column.
    assert profile["numeric_column_count"] == 1
    assert profile["categorical_column_count"] == 2
    assert _column(profile, "a")["classification"] == "numeric"


def test_all_blank_csv_column_is_not_numeric() -> None:
    df = parse_dataset(_BLANK_CSV, FileType.CSV, UploadLimits.defaults())
    assert str(df["empty"].dtype) == "float64"  # the trap: pandas infers float64
    _all_missing_checks(df)


def test_all_blank_xlsx_column_is_not_numeric() -> None:
    frame = pd.DataFrame({"a": [1, 2, 3, 4], "empty": [None] * 4, "b": list("xyxy")})
    df = parse_dataset(_xlsx(frame), FileType.XLSX, UploadLimits.defaults())
    _all_missing_checks(df)


def test_all_missing_column_is_not_in_the_numeric_statistics() -> None:
    df = parse_dataset(_BLANK_CSV, FileType.CSV, UploadLimits.defaults())
    profile = profile_dataset(df, inspect_data_quality=True)
    classifications = {c["name"]: c["classification"] for c in profile["columns"]}
    stats = compute_descriptive_stats(df, classifications)
    assert [c["column"] for c in stats["columns"]] == ["a"]
    assert stats["numeric_column_count"] == 1
    assert "empty" in stats["skipped_columns"]


def test_all_missing_object_and_datetime_columns_are_not_dates_or_numbers() -> None:
    assert _classify_column(pd.Series([None, None, None], dtype=object)) == "categorical"
    assert _classify_column(pd.Series([pd.NaT, pd.NaT], dtype="datetime64[ns]")) == "categorical"


def test_partially_missing_numeric_column_stays_numeric_with_valid_statistics() -> None:
    content = b"a,partial\n1,10\n2,\n3,30\n4,\n5,50\n"
    df = parse_dataset(content, FileType.CSV, UploadLimits.defaults())
    profile = profile_dataset(df, inspect_data_quality=True)
    partial = _column(profile, "partial")
    assert partial["classification"] == "numeric"
    assert partial["missing_count"] == 2
    assert (partial["min_value"], partial["max_value"]) == (10.0, 50.0)
    classifications = {c["name"]: c["classification"] for c in profile["columns"]}
    result = compute_descriptive_stats(df, classifications)
    stats = {s["column"]: s for s in result["columns"]}
    assert stats["partial"]["mean"] == pytest.approx(30.0)
    assert stats["partial"]["count"] == 3


def test_partially_missing_numeric_column_stays_numeric_from_xlsx() -> None:
    frame = pd.DataFrame({"a": [1, 2, 3], "partial": [1.5, None, 4.5]})
    df = parse_dataset(_xlsx(frame), FileType.XLSX, UploadLimits.defaults())
    assert _column(profile_dataset(df), "partial")["classification"] == "numeric"


def test_zero_row_frame_keeps_its_dtype_classification() -> None:
    assert _classify_column(pd.Series([], dtype="float64")) == "numeric"


# --- 2. dot-separated dates -------------------------------------------------


def _date_profile(values: list[str]) -> dict[str, Any]:
    return profile_dataset(
        pd.DataFrame({"d": values, "v": range(len(values))}), inspect_data_quality=True
    )


def test_ambiguous_dotted_dates_are_dates_with_a_warning() -> None:
    profile = _date_profile(["01.02.2025", "03.04.2025", "05.06.2025", "07.08.2025"] * 3)
    d = _column(profile, "d")
    assert d["classification"] == "date"
    assert d["date_order_issue"] == "ambiguous"
    assert profile["date_column_count"] == 1
    note = next(n for n in profile["import_notes"] if n["code"] == "ambiguous_dates")
    assert note["severity"] == "warning" and note["columns"] == ["d"]


def test_dotted_dates_from_csv_and_xlsx_end_to_end() -> None:
    values = ["01.02.2025", "03.04.2025", "05.06.2025", "07.08.2025"] * 3
    frame = pd.DataFrame({"d": values, "v": range(12)})
    csv = frame.to_csv(index=False).encode()
    for content, file_type in ((csv, FileType.CSV), (_xlsx(frame), FileType.XLSX)):
        df, notes = parse_dataset_with_notes(content, file_type, UploadLimits.defaults())
        profile = profile_dataset(df, inspect_data_quality=True, import_notes=notes)
        assert _column(profile, "d")["classification"] == "date"
        assert "ambiguous_dates" in _codes(profile)


def test_dotted_dates_that_prove_an_order_are_dates_without_a_warning() -> None:
    profile = _date_profile(["25.12.2025", "26.01.2025", "27.02.2025", "28.03.2025"] * 3)
    d = _column(profile, "d")
    assert d["classification"] == "date" and d["date_order_issue"] is None
    assert "ambiguous_dates" not in _codes(profile)


def test_dotted_dates_with_two_digit_years_are_dates() -> None:
    profile = _date_profile(["01.02.25", "03.04.25", "05.06.25", "07.08.25"] * 3)
    assert _column(profile, "d")["classification"] == "date"


@pytest.mark.parametrize(
    ("values", "expected", "issue"),
    [
        (["2025-01-02", "2025-03-04", "2025-05-06"] * 4, "date", None),  # ISO
        (["03/04/2025", "05/06/2025", "01/02/2025"] * 4, "date", "ambiguous"),  # slash
        (["03-04-2025", "05-06-2025", "01-02-2025"] * 4, "date", "ambiguous"),  # hyphen
        (["25/12/2025", "26/01/2025", "27/02/2025"] * 4, "date", None),  # unambiguous
        (["Jan 5 2025", "Feb 6 2025", "Mar 7 2025"] * 4, "date", None),  # month names
    ],
)
def test_existing_date_formats_are_unchanged(
    values: list[str], expected: str, issue: str | None
) -> None:
    d = _column(_date_profile(values), "d")
    assert d["classification"] == expected and d["date_order_issue"] == issue


@pytest.mark.parametrize(
    "values",
    [
        ["1.5", "2.3", "4.7", "10.25"] * 5,  # decimals kept as text
        ["v1.2", "v1.3", "v2.0", "v2.1"] * 5,  # versions
        ["1.2.3", "1.2.4", "2.0.1", "3.1.0"] * 5,  # semantic versions
        ["20260115", "20260116", "20260117", "20260118"] * 5,  # separator-less digits
    ],
)
def test_dot_support_does_not_turn_other_text_into_dates(values: list[str]) -> None:
    assert _classify_column(pd.Series(values)) == "categorical"


# --- 3. legacy (pre-Stage 3) uploads ----------------------------------------

_NA_CSV = b"code,score\nUS,1\nNA,2\nDE,NA\nNA,4\n"


def test_legacy_policy_reads_na_as_missing_exactly_like_stock_pandas() -> None:
    legacy = parse_dataset(_NA_CSV, FileType.CSV, legacy_na_policy=True)
    stock = pd.read_csv(io.BytesIO(_NA_CSV), index_col=False)
    pd.testing.assert_frame_equal(legacy, stock)
    assert int(legacy["code"].isna().sum()) == 2


def test_legacy_policy_reads_na_as_missing_in_xlsx_too() -> None:
    content = _xlsx(pd.DataFrame({"code": ["US", "NA", "DE"], "n": [1, 2, 3]}))
    legacy = parse_dataset(content, FileType.XLSX, legacy_na_policy=True)
    stock = pd.read_excel(io.BytesIO(content), sheet_name=0)
    pd.testing.assert_frame_equal(legacy, stock)
    assert int(legacy["code"].isna().sum()) == 1


def test_stage_3_policy_is_still_the_default() -> None:
    df = parse_dataset(_NA_CSV, FileType.CSV)
    assert int(df["code"].isna().sum()) == 0 and (df["code"] == "NA").sum() == 2


def test_legacy_policy_produces_no_notes_and_keeps_limits() -> None:
    _, notes = parse_dataset_with_notes(_NA_CSV, FileType.CSV, legacy_na_policy=True)
    assert notes == []
    with pytest.raises(Exception, match="rows"):
        parse_dataset(_NA_CSV, FileType.CSV, UploadLimits(max_rows=2), legacy_na_policy=True)


def test_legacy_profile_agrees_with_the_legacy_reread() -> None:
    """What a pre-Stage-3 upload stored (stock-pandas parse, no import_notes) is
    what the analysis re-read now reproduces."""
    stored = profile_dataset(pd.read_csv(io.BytesIO(_NA_CSV), index_col=False))
    reread = profile_dataset(parse_dataset(_NA_CSV, FileType.CSV, legacy_na_policy=True))
    assert reread == stored
    assert _column(stored, "code")["missing_count"] == 2


@pytest.mark.parametrize(
    ("profile", "legacy"),
    [
        (None, True),  # no stored profile at all
        ({"row_count": 1, "columns": []}, True),  # pre-Stage-3 shape
        ({"row_count": 1, "columns": [], "import_notes": []}, False),  # Stage 3, no findings
        ({"row_count": 1, "columns": [], "import_notes": [{"code": "x"}]}, False),
    ],
)
def test_legacy_upload_marker(profile: dict[str, Any] | None, legacy: bool) -> None:
    assert is_legacy_upload(profile) is legacy


def test_every_new_upload_profile_carries_the_stage_3_marker() -> None:
    df = parse_dataset(b"a\n1\n2\n", FileType.CSV, UploadLimits.defaults())
    profile = profile_dataset(df, inspect_data_quality=True, import_notes=[])
    assert profile["import_notes"] == [] and not is_legacy_upload(profile)
