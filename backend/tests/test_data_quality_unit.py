"""Stage 3 (generic data correctness) - unit tests for app.analytics.data_quality
and the parse/profile wiring. Pure DataFrame/bytes in, no DB or HTTP."""

from __future__ import annotations

import io
from typing import Any

import numpy as np
import pandas as pd
import pytest

from app.analytics import data_quality as dq
from app.analytics.profiling import profile_dataset
from app.models import FileType
from app.services.file_service import (
    UploadLimits,
    parse_dataset,
    parse_dataset_with_notes,
)


def _codes(notes: list[dq.ImportNote]) -> list[str]:
    return [n["code"] for n in notes]


def _note(notes: list[dq.ImportNote], code: str) -> dq.ImportNote:
    return next(n for n in notes if n["code"] == code)


def _csv(text: str) -> bytes:
    return text.encode("utf-8")


def _xlsx(sheets: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, index=False)
    return buf.getvalue()


# --- 1. "NA" -------------------------------------------------------------


def test_na_in_a_numeric_column_is_missing_and_reported() -> None:
    df, notes = parse_dataset_with_notes(_csv("x,y\n1,a\nNA,b\n3,c\n"), FileType.CSV)
    assert pd.api.types.is_numeric_dtype(df["x"])
    assert int(df["x"].isna().sum()) == 1
    note = _note(notes, "na_text_read_as_missing")
    assert note["columns"] == ["x"]
    assert note["details"]["cells_by_column"] == {"x": 1}
    assert note["severity"] == "info"


def test_na_in_a_text_column_is_kept_as_a_value_and_reported() -> None:
    df, notes = parse_dataset_with_notes(_csv("country,n\nNA,1\nUS,2\nNA,3\n"), FileType.CSV)
    assert df["country"].tolist() == ["NA", "US", "NA"]
    assert int(df["country"].isna().sum()) == 0
    note = _note(notes, "na_text_kept_as_value")
    assert note["columns"] == ["country"]
    assert note["severity"] == "warning"
    assert "Namibia" in note["message"]


def test_column_that_is_only_na_is_kept_not_invented_as_missing() -> None:
    df, notes = parse_dataset_with_notes(_csv("a,b\nNA,1\nNA,2\n"), FileType.CSV)
    assert df["a"].tolist() == ["NA", "NA"]
    assert "na_text_kept_as_value" in _codes(notes)


def test_other_missing_tokens_behave_as_before() -> None:
    content = _csv("v,w\n1,a\n,b\nN/A,c\nnull,d\nNaN,e\n#N/A,f\nn/a,g\nNone,h\n2,i\n")
    df, notes = parse_dataset_with_notes(content, FileType.CSV)
    stock = pd.read_csv(io.BytesIO(content), index_col=False)  # pandas defaults
    pd.testing.assert_frame_equal(df, stock)
    assert int(df["v"].isna().sum()) == 7
    assert notes == []


def test_na_handling_applies_to_xlsx_too() -> None:
    frame = pd.DataFrame({"x": [1, "NA", 3], "c": ["NA", "b", "c"]})
    df, notes = parse_dataset_with_notes(_xlsx({"Sheet1": frame}), FileType.XLSX)
    assert pd.api.types.is_numeric_dtype(df["x"]) and int(df["x"].isna().sum()) == 1
    assert df["c"].tolist() == ["NA", "b", "c"]
    assert {"na_text_read_as_missing", "na_text_kept_as_value"} <= set(_codes(notes))


def test_file_without_na_text_is_parsed_exactly_as_before() -> None:
    content = _csv("a,b,c\n1,x,2.5\n2,y,\n3,z,4.5\n")
    new = parse_dataset(content, FileType.CSV)
    old = pd.read_csv(io.BytesIO(content), index_col=False)
    pd.testing.assert_frame_equal(new, old)


def test_stored_file_reread_matches_the_upload_parse() -> None:
    content = _csv("x,k\n1,NA\nNA,b\n3,c\n")
    with_limits = parse_dataset(content, FileType.CSV, UploadLimits.defaults())
    without = parse_dataset(content, FileType.CSV)  # analysis re-read path
    pd.testing.assert_frame_equal(with_limits, without)


# --- 2. XLSX sheets ------------------------------------------------------


def test_extra_sheets_are_named_and_first_sheet_is_still_the_one_read() -> None:
    content = _xlsx(
        {"Sales": pd.DataFrame({"a": [1, 2]}), "Q2": pd.DataFrame({"z": [9]}), "Q3": pd.DataFrame()}
    )
    df, notes = parse_dataset_with_notes(content, FileType.XLSX, UploadLimits.defaults())
    assert list(df.columns) == ["a"]
    note = _note(notes, "xlsx_extra_sheets")
    assert note["details"] == {"analysed_sheet": "Sales", "ignored_sheets": ["Q2", "Q3"]}
    assert "Sales" in note["message"] and "Q2" in note["message"]


def test_single_sheet_workbook_has_no_sheet_note() -> None:
    _, notes = parse_dataset_with_notes(_xlsx({"Only": pd.DataFrame({"a": [1]})}), FileType.XLSX)
    assert "xlsx_extra_sheets" not in _codes(notes)


def test_sheet_name_reader_never_raises_on_garbage() -> None:
    from app.services.file_service import _xlsx_sheet_names

    assert _xlsx_sheet_names(b"not a zip") == []


# --- headers -------------------------------------------------------------


def test_duplicate_and_blank_headers_are_reported() -> None:
    df, notes = parse_dataset_with_notes(_csv("price,price,,qty\n1,2,3,4\n"), FileType.CSV)
    assert list(df.columns) == ["price", "price.1", "Unnamed: 2", "qty"]  # pandas' own names
    assert _note(notes, "duplicate_headers")["details"]["renamed_from"] == {"price.1": "price"}
    assert _note(notes, "blank_headers")["columns"] == ["Unnamed: 2"]


def test_clean_headers_produce_no_header_notes() -> None:
    assert dq.detect_header_issues(["a", "b.c", "price.1x"]) == []


# --- 3. identifiers ------------------------------------------------------


def test_sequential_integer_column_is_flagged() -> None:
    assert dq.detect_identifier(pd.Series(range(1, 51)), "numeric") == "sequential_integers"
    assert dq.detect_identifier(pd.Series([1001 + i * 1 for i in range(40)]), "numeric")


def test_sequential_with_a_few_gaps_is_flagged() -> None:
    values = [i for i in range(1, 61) if i % 10 != 0]
    assert dq.detect_identifier(pd.Series(values), "numeric") == "sequential_integers"


@pytest.mark.parametrize(
    "series",
    [
        pd.Series(np.linspace(0.5, 99.5, 50)),  # continuous measurement
        pd.Series(list(range(1, 26)) * 2),  # repeated values
        pd.Series(range(2000, 2030)),  # calendar years
        pd.Series([i * 1000 + 7 for i in range(30)]),  # unique ints with big gaps
        pd.Series(range(1, 11)),  # too few values to judge
    ],
)
def test_ordinary_numeric_columns_are_not_flagged(series: pd.Series) -> None:
    assert dq.detect_identifier(series, "numeric") is None


def test_unique_text_is_flagged_but_categories_are_not() -> None:
    names = pd.Series([f"customer-{i}" for i in range(40)])
    assert dq.detect_identifier(names, "categorical") == "unique_text"
    assert dq.detect_identifier(pd.Series(["a", "b", "c", "d"] * 10), "categorical") is None


def test_identifier_is_flagged_not_dropped() -> None:
    df = pd.DataFrame({"row": range(1, 41), "v": np.arange(40) * 1.5})
    profile = profile_dataset(df, inspect_data_quality=True)
    assert profile["column_count"] == 2
    row = next(c for c in profile["columns"] if c["name"] == "row")
    assert row["likely_identifier"] is True and row["classification"] == "numeric"
    note = _note(profile["import_notes"], "likely_identifier_columns")
    assert note["columns"] == ["row"] and "still included" in note["message"]


# --- 4. number formats ---------------------------------------------------


@pytest.mark.parametrize(
    ("values", "kind"),
    [
        (["$1,200.50", "$30", "$4,000", "($50.00)"], "currency"),
        (["€12", "12,50 €", "€1.234,56"], "currency"),
        (["45%", "12.5 %", "100%", "7%"], "percent"),
        (["1,234", "12,345,678", "999", "10,000.5"], "thousands"),
    ],
)
def test_formatted_numbers_are_identified(values: list[str], kind: str) -> None:
    result = dq.detect_number_format(pd.Series(values * 3))
    assert result is not None and result[0] == kind and len(result[1]) <= 3


@pytest.mark.parametrize(
    "values",
    [
        ["red", "green", "blue"],
        ["12", "15", "18"],  # plain digits: not a formatted number (and not text-typed by pandas)
        ["$5", "red", "blue", "green", "x"],  # below the 90% bar
        ["1,2", "3,4", "5,6"],  # decimal commas / pairs, not thousands groups
    ],
)
def test_other_text_is_not_flagged_as_formatted_numbers(values: list[str]) -> None:
    assert dq.detect_number_format(pd.Series(values)) is None


def test_formatted_column_stays_categorical_and_unconverted() -> None:
    df = pd.DataFrame({"price": ["$1,200", "$30", "$450"] * 10, "n": range(30)})
    profile = profile_dataset(df, inspect_data_quality=True)
    price = next(c for c in profile["columns"] if c["name"] == "price")
    assert price["classification"] == "categorical" and price["number_format"] == "currency"
    assert price["likely_identifier"] is False  # distinct strings, but they are numbers
    note = _note(profile["import_notes"], "formatted_numbers_as_text")
    assert "e.g. '$1,200'" in note["message"] or "e.g. '$30'" in note["message"]
    assert df["price"].iloc[0] == "$1,200"
    assert "formatted_numbers_as_text" in _codes(profile["import_notes"])


# --- 5. dates --------------------------------------------------------------


def _dates(values: list[str]) -> pd.Series:
    return pd.Series(values * 5)


def test_dates_where_nothing_settles_the_order_are_ambiguous() -> None:
    assert dq.detect_date_order_issue(_dates(["03/04/2024", "05/06/2024", "01/02/2024"])) == (
        "ambiguous"
    )


def test_dates_mixing_both_orders_are_inconsistent() -> None:
    assert dq.detect_date_order_issue(_dates(["13/04/2024", "04/13/2024", "03/04/2024"])) == (
        "inconsistent"
    )


def test_order_proven_but_some_rows_unclear_is_partly_ambiguous() -> None:
    assert dq.detect_date_order_issue(_dates(["13/04/2024", "03/04/2024"])) == "partly_ambiguous"


@pytest.mark.parametrize(
    "values",
    [
        ["2024-04-03", "2024-05-06"],  # ISO
        ["13/04/2024", "25/12/2024"],  # every row proves day-first
        ["04/13/2024", "12/25/2024"],  # every row proves month-first
        ["05/05/2024", "01/01/2024"],  # same number either way: not ambiguous
        ["Jan 5 2024", "Feb 6 2024"],
    ],
)
def test_unambiguous_dates_are_not_flagged(values: list[str]) -> None:
    assert dq.detect_date_order_issue(_dates(values)) is None


def test_ambiguous_date_column_is_still_classified_as_a_date() -> None:
    df = pd.DataFrame({"d": ["03/04/2024", "05/06/2024", "01/02/2024"] * 4, "v": range(12)})
    profile = profile_dataset(df, inspect_data_quality=True)
    d = next(c for c in profile["columns"] if c["name"] == "d")
    assert d["classification"] == "date" and d["date_order_issue"] == "ambiguous"
    assert "ambiguous_dates" in _codes(profile["import_notes"])


# --- profile compatibility -------------------------------------------------


def test_profile_without_inspection_has_no_new_keys() -> None:
    df = pd.DataFrame({"a": range(30), "b": ["x"] * 30})
    profile = profile_dataset(df)
    assert "import_notes" not in profile
    assert set(profile["columns"][0]) == {
        "name",
        "classification",
        "pandas_dtype",
        "missing_count",
        "missing_percentage",
        "unique_count",
        "is_unique",
        "min_value",
        "max_value",
    }


def test_profile_stored_before_stage_3_still_validates() -> None:
    from app.schemas.upload import DatasetProfile

    old: dict[str, Any] = {
        "row_count": 1,
        "column_count": 1,
        "numeric_column_count": 1,
        "categorical_column_count": 0,
        "date_column_count": 0,
        "total_missing_values": 0,
        "duplicate_row_count": 0,
        "columns": [
            {
                "name": "a",
                "classification": "numeric",
                "pandas_dtype": "int64",
                "missing_count": 0,
                "missing_percentage": 0.0,
                "unique_count": 1,
                "is_unique": True,
            }
        ],
    }
    profile = DatasetProfile.model_validate(old)
    assert profile.import_notes == [] and profile.columns[0].likely_identifier is False
