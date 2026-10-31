"""
Stage 3 (generic data correctness): detect-and-explain helpers.

Rule for everything in this module: it never drops or rewrites the user's
data to make a problem go away. It either leaves the data exactly as
parsed and *reports* what looks wrong (identifier columns, currency/percent
text, ambiguous dates, renamed headers, ignored sheets), or - in the one
place a value is interpreted, the text "NA" - it records exactly what it
did. Every finding is an "import note": a small dict that is stored inside
the dataset profile and shown to the user.

Pure functions only (DataFrame/Series in, plain data out): no DB, no I/O.
"""

from __future__ import annotations

import re
from typing import Any, Literal, TypedDict

import numpy as np
import pandas as pd

Severity = Literal["info", "warning"]

# pandas' default missing-value tokens EXCEPT "NA". "NA" is handled by
# `resolve_na_text` because it is genuinely ambiguous (R-style "not
# available" in a numeric column vs. a real value such as the country code
# for Namibia or the category "North America" in a text column).
NA_TOKENS_WITHOUT_NA: tuple[str, ...] = (
    "",
    "#N/A",
    "#N/A N/A",
    "#NA",
    "-1.#IND",
    "-1.#QNAN",
    "-NaN",
    "-nan",
    "1.#IND",
    "1.#QNAN",
    "<NA>",
    "N/A",
    "NULL",
    "NaN",
    "None",
    "n/a",
    "nan",
    "null",
)

# A column needs at least this many non-missing values before it can be
# called an identifier: a 5-row table of distinct names is just a small table.
IDENTIFIER_MIN_VALUES = 20
IDENTIFIER_TEXT_MIN_UNIQUE_FRACTION = 0.98
# Whole-number sequences inside this window look like calendar years, which
# are a meaningful (time) variable, not an identifier.
_YEAR_RANGE = (1800, 2200)

_FORMAT_SAMPLE_SIZE = 1000
_FORMAT_MIN_FRACTION = 0.9
_FORMAT_MAX_EXAMPLES = 3

_CURRENCY_SYMBOLS = "$€£¥₹"
_NUMBER_BODY = r"\d[\d.,]*"
_PERCENT_RE = re.compile(rf"^[+-]?{_NUMBER_BODY}\s?%$")
_CURRENCY_RE = re.compile(
    rf"^\(?[+-]?\s?[{_CURRENCY_SYMBOLS}]\s?[+-]?{_NUMBER_BODY}\)?$"
    rf"|^[+-]?{_NUMBER_BODY}\s?[{_CURRENCY_SYMBOLS}]$"
)
_THOUSANDS_RE = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})*(?:\.\d+)?$")

# d/m/y-style numeric dates, year last: 03/04/2024, 3-4-24, 03.04.2024
# (an optional time part after a space or "T" is ignored).
_NUMERIC_DATE_RE = re.compile(r"^\s*(\d{1,2})[/.\-](\d{1,2})[/.\-](?:\d{2}|\d{4})(?:[ T].*)?$")
_DATE_STYLE_MIN_FRACTION = 0.9

_UNNAMED_RE = re.compile(r"^Unnamed: \d+$")
_MANGLED_DUPLICATE_RE = re.compile(r"^(?P<base>.+)\.(?P<n>\d+)$")

_MAX_LISTED_NAMES = 20


class ImportNote(TypedDict):
    code: str
    severity: Severity
    message: str
    columns: list[str]
    details: dict[str, Any]


def make_note(
    code: str,
    severity: Severity,
    message: str,
    columns: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> ImportNote:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "columns": columns or [],
        "details": details or {},
    }


def _quoted(names: list[str]) -> str:
    shown = [f"'{n}'" for n in names[:_MAX_LISTED_NAMES]]
    extra = len(names) - len(shown)
    return ", ".join(shown) + (f" and {extra} more" if extra > 0 else "")


def _is_text_dtype(series: pd.Series) -> bool:
    """True for string-like columns under both the pandas 2 (object) and
    pandas 3 (str) default dtypes. Numeric, bool and datetime are not text."""
    if (
        pd.api.types.is_bool_dtype(series)
        or pd.api.types.is_numeric_dtype(series)
        or pd.api.types.is_datetime64_any_dtype(series)
    ):
        return False
    return True


def _string_values(series: pd.Series) -> pd.Series:
    """Non-null values as stripped strings (mixed int/str object columns from
    Excel are stringified so the same patterns apply)."""
    return series.dropna().astype(str).str.strip()


# --- 1. the text "NA" ---------------------------------------------------


def resolve_na_text(df: pd.DataFrame) -> tuple[pd.DataFrame, list[ImportNote]]:
    """Decide what the literal text "NA" means, column by column, and say so.

    The parser is told NOT to treat "NA" as missing, so it arrives here as
    text. Then, per column that contains it:

    * every other non-missing value is a number -> "NA" is a missing-value
      marker; it becomes a real missing value and the column becomes numeric;
    * otherwise (a text column, or a column that is only "NA") -> it is a
      genuine value and is kept exactly as written.

    Either way the user is told how many cells were affected.
    """
    notes: list[ImportNote] = []
    result = df
    as_missing: list[str] = []
    kept_as_text: list[str] = []
    counts: dict[str, int] = {}

    for position, column in enumerate(df.columns):
        series = df.iloc[:, position]
        if not _is_text_dtype(series):
            continue
        is_na_text = series.eq("NA").fillna(False).to_numpy(dtype=bool)
        na_count = int(is_na_text.sum())
        if na_count == 0:
            continue

        name = str(column)
        counts[name] = na_count
        others = series[~is_na_text].dropna()
        numeric = pd.to_numeric(others, errors="coerce")
        if len(others) > 0 and bool(numeric.notna().all()):
            if result is df:
                result = df.copy()
            cleaned = series.mask(is_na_text, np.nan)
            result.isetitem(position, pd.to_numeric(cleaned).to_numpy())
            as_missing.append(name)
        else:
            kept_as_text.append(name)

    if as_missing:
        total = sum(counts[n] for n in as_missing)
        notes.append(
            make_note(
                "na_text_read_as_missing",
                "info",
                f"The text 'NA' was read as a missing value in {_quoted(as_missing)} "
                f"({total:,} cell{'s' if total != 1 else ''}), because every other value in "
                f"{'that column' if len(as_missing) == 1 else 'those columns'} is a number.",
                as_missing,
                {"cells_by_column": {n: counts[n] for n in as_missing}},
            )
        )
    if kept_as_text:
        total = sum(counts[n] for n in kept_as_text)
        notes.append(
            make_note(
                "na_text_kept_as_value",
                "warning",
                f"The text 'NA' was kept as a real value, not as missing, in "
                f"{_quoted(kept_as_text)} ({total:,} cell{'s' if total != 1 else ''}), because "
                f"{'that column holds' if len(kept_as_text) == 1 else 'those columns hold'} text "
                "(it could be a code such as Namibia). If 'NA' means 'not available' there, "
                "leave those cells blank and upload again.",
                kept_as_text,
                {"cells_by_column": {n: counts[n] for n in kept_as_text}},
            )
        )
    return result, notes


# --- 2. headers ---------------------------------------------------------


def detect_header_issues(columns: list[str]) -> list[ImportNote]:
    """Blank and duplicate headers. pandas silently names a blank header
    'Unnamed: N' and renames the second 'price' to 'price.1'; both are
    recognised from the resulting names (a header the user really wrote as
    'price.1' next to 'price' is indistinguishable and is reported too -
    the note says 'looks like')."""
    notes: list[ImportNote] = []
    names = [str(c) for c in columns]
    present = set(names)

    blank = [n for n in names if _UNNAMED_RE.match(n)]
    if blank:
        notes.append(
            make_note(
                "blank_headers",
                "warning",
                f"{len(blank)} column{'s have' if len(blank) != 1 else ' has'} no header "
                f"and {'were' if len(blank) != 1 else 'was'} named automatically: "
                f"{_quoted(blank)}. Add a header in the first row if you want a real name.",
                blank,
            )
        )

    renamed: dict[str, str] = {}
    for name in names:
        match = _MANGLED_DUPLICATE_RE.match(name)
        if match and match.group("base") in present:
            renamed[name] = match.group("base")
    if renamed:
        listed = [f"'{new}' (same header as '{old}')" for new, old in list(renamed.items())[:10]]
        notes.append(
            make_note(
                "duplicate_headers",
                "warning",
                "Some columns share a header and look like they were renamed automatically: "
                f"{', '.join(listed)}. Give each column its own header to avoid confusion.",
                list(renamed),
                {"renamed_from": renamed},
            )
        )
    return notes


# --- 3. identifier-like columns ------------------------------------------


def detect_identifier(series: pd.Series, classification: str) -> str | None:
    """Reason code if the column looks like a row identifier, else None.

    Decided from the data, not from the column name:

    * "sequential_integers" - whole numbers, all distinct, forming a (nearly)
      unbroken run, e.g. 1..N or 1001..1500 with a few gaps. Windows that
      look like calendar years are excluded.
    * "unique_text" - text where (nearly) every value is different, so it
      cannot be used to group rows.

    Needs IDENTIFIER_MIN_VALUES non-missing values. Random-looking numeric
    IDs with big gaps are deliberately NOT flagged: a unique whole-number
    measurement (a salary, a population) looks the same.
    """
    non_null = series.dropna()
    n = len(non_null)
    if n < IDENTIFIER_MIN_VALUES or pd.api.types.is_bool_dtype(series):
        return None

    if classification == "numeric":
        values = pd.to_numeric(non_null, errors="coerce").to_numpy(dtype=float)
        if not bool(np.isfinite(values).all()) or not bool((values == np.floor(values)).all()):
            return None
        if len(np.unique(values)) != n:
            return None
        low, high = float(values.min()), float(values.max())
        if (high - low + 1) > 1.5 * n:
            return None
        if _YEAR_RANGE[0] <= low and high <= _YEAR_RANGE[1]:
            return None
        return "sequential_integers"

    if classification == "categorical" and _is_text_dtype(series):
        unique_fraction = non_null.nunique() / n
        if unique_fraction >= IDENTIFIER_TEXT_MIN_UNIQUE_FRACTION:
            return "unique_text"
    return None


def identifier_note(columns_by_reason: dict[str, list[str]]) -> ImportNote | None:
    names = [n for group in columns_by_reason.values() for n in group]
    if not names:
        return None
    return make_note(
        "likely_identifier_columns",
        "info",
        f"{_quoted(names)} look{'s' if len(names) == 1 else ''} like "
        f"{'an identifier' if len(names) == 1 else 'identifiers'} (row numbers or "
        "values that are almost all different). "
        f"{'It is' if len(names) == 1 else 'They are'} still included in the analysis, so "
        "correlations, outliers and regression that involve "
        f"{'it' if len(names) == 1 else 'them'} will not be meaningful.",
        names,
        {"reasons": columns_by_reason},
    )


# --- 4. currency / percent / thousands text ------------------------------


def detect_number_format(series: pd.Series) -> tuple[str, list[str]] | None:
    """('currency' | 'percent' | 'thousands', examples) when a text column is
    really formatted numbers; None otherwise. Looks at a deterministic sample
    and needs >= 90% of it to match one format."""
    if not _is_text_dtype(series):
        return None
    values = _string_values(series)
    if values.empty:
        return None
    if len(values) > _FORMAT_SAMPLE_SIZE:
        values = values.sample(_FORMAT_SAMPLE_SIZE, random_state=0)

    for kind, pattern in (
        ("percent", _PERCENT_RE),
        ("currency", _CURRENCY_RE),
        ("thousands", _THOUSANDS_RE),
    ):
        matches = values.str.match(pattern)
        if float(matches.mean()) < _FORMAT_MIN_FRACTION:
            continue
        if kind == "thousands" and not bool(values[matches].str.contains(",").any()):
            continue
        examples = list(dict.fromkeys(values[matches].tolist()))[:_FORMAT_MAX_EXAMPLES]
        return kind, examples
    return None


_FORMAT_LABEL = {"currency": "currency amounts", "percent": "percentages", "thousands": "numbers"}


def number_format_note(formats: dict[str, tuple[str, list[str]]]) -> ImportNote | None:
    if not formats:
        return None
    parts = []
    for name, (kind, examples) in formats.items():
        shown = ", ".join(f"'{e}'" for e in examples)
        parts.append(f"'{name}' ({_FORMAT_LABEL[kind]} written as text, e.g. {shown})")
    names = list(formats)
    return make_note(
        "formatted_numbers_as_text",
        "warning",
        f"{'; '.join(parts)}. "
        f"{'This column is' if len(names) == 1 else 'These columns are'} treated as categories, "
        "not numbers, so no statistics or regression are computed for "
        f"{'it' if len(names) == 1 else 'them'}. Zaimex does not convert these values "
        "automatically (for example '1,234' means different numbers in different locales); "
        "remove the symbols and separators in your file and upload again to analyse "
        f"{'it' if len(names) == 1 else 'them'} as numbers.",
        names,
        {"formats": {n: {"kind": k, "examples": e} for n, (k, e) in formats.items()}},
    )


# --- 5. ambiguous dates --------------------------------------------------


def detect_date_order_issue(series: pd.Series) -> str | None:
    """For a text column of numeric d/m/y dates, whether the day/month order
    is a problem:

    * "ambiguous"          - no value proves an order (all of day and month <= 12)
    * "inconsistent"       - some values prove day-first and others month-first
    * "partly_ambiguous"   - the order is proven one way, but some values
                             could be read either way

    None when the column is not in this style, or the order is unambiguous
    (ISO dates, or at least one value > 12 and no value that could go either
    way).
    """
    if not _is_text_dtype(series):
        return None
    values = _string_values(series)
    if values.empty:
        return None
    parts = values.str.extract(_NUMERIC_DATE_RE)
    matched = parts[0].notna()
    if float(matched.mean()) < _DATE_STYLE_MIN_FRACTION:
        return None
    first = parts.loc[matched, 0].astype(int)
    second = parts.loc[matched, 1].astype(int)
    day_first = int((first > 12).sum())  # first number can only be a day
    month_first = int((second > 12).sum())  # second number can only be a day
    either = int(((first <= 12) & (second <= 12) & (first != second)).sum())

    if day_first and month_first:
        return "inconsistent"
    if day_first == 0 and month_first == 0:
        return "ambiguous" if either else None
    return "partly_ambiguous" if either else None


_DATE_ISSUE_TEXT = {
    "ambiguous": "could mean day/month or month/day and nothing in the column settles it",
    "inconsistent": "mix day/month and month/day orders",
    "partly_ambiguous": (
        "are written in one order for some rows, but other rows could be read either way"
    ),
}


def date_order_note(issues: dict[str, str]) -> ImportNote | None:
    if not issues:
        return None
    parts = [f"'{name}' ({_DATE_ISSUE_TEXT[issue]})" for name, issue in issues.items()]
    names = list(issues)
    return make_note(
        "ambiguous_dates",
        "warning",
        f"Dates in {'; '.join(parts)}. Zaimex does not convert dates and cannot tell which order "
        "is meant. If you rely on "
        f"{'this column' if len(names) == 1 else 'these columns'}, write dates in an unambiguous "
        "form such as 2024-04-03.",
        names,
        {"issues": issues},
    )


# --- 6. extra worksheets -------------------------------------------------


def extra_sheets_note(sheet_names: list[str]) -> ImportNote | None:
    if len(sheet_names) <= 1:
        return None
    first, ignored = sheet_names[0], sheet_names[1:]
    return make_note(
        "xlsx_extra_sheets",
        "warning",
        f"This workbook has {len(sheet_names)} sheets. Only the first sheet, '{first}', was "
        f"analysed; these were ignored: {_quoted(ignored)}. Upload one sheet per project, or "
        "move the data you need to the first sheet.",
        [],
        {"analysed_sheet": first, "ignored_sheets": ignored[:_MAX_LISTED_NAMES]},
    )
