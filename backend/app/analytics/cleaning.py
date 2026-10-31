"""
Transparent, configurable data cleaning.

Generalizes StatFlow's two hardcoded n8n nodes (Phase 1 audit S7): a
`Remove Duplicates` keyed to a literal `Order_ID` column, and a `Filter`
that silently dropped rows missing three specific retail columns. Both
are replaced here by explicit, column-agnostic choices that always
report exactly what changed.

Two rules drive the design:

1. Nothing is silent. Every action is reported back with counts, so the
   Phase 2 Data Quality tab can show the user precisely what happened
   to their data rather than presenting altered numbers as if they were
   the originals.
2. Nothing is destructive. The caller's DataFrame is never mutated - a
   copy is returned - and the uploaded source file in object storage is
   never touched. The cleaned dataset is a derived artifact.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

from app.analytics._common import safe_float

NumericStrategy = Literal["median", "unchanged"]
CategoricalStrategy = Literal["mode", "unchanged"]
DuplicateStrategy = Literal["remove", "keep"]


@dataclass(frozen=True)
class CleaningConfig:
    """Explicit, structured, reproducible. Stored on the analysis row so
    a past run's exact cleaning choices can always be reconstructed.

    Defaults are the conservative ones from the approved spec: impute
    rather than drop rows (imputation preserves every observation),
    but keep duplicates unless the user actively opts into removal,
    since duplicate rows are sometimes legitimately repeated
    measurements rather than data-entry errors - the engine can't tell
    which, so it doesn't guess.
    """

    numeric_strategy: NumericStrategy = "median"
    categorical_strategy: CategoricalStrategy = "mode"
    duplicate_strategy: DuplicateStrategy = "keep"

    def to_dict(self) -> dict[str, str]:
        return {
            "numeric_strategy": self.numeric_strategy,
            "categorical_strategy": self.categorical_strategy,
            "duplicate_strategy": self.duplicate_strategy,
        }


def clean_dataset(
    df: pd.DataFrame,
    classifications: dict[str, str],
    config: CleaningConfig | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Apply the chosen strategy, returning (cleaned_df, report).

    Args:
        df: the parsed dataset. Never mutated.
        classifications: the profiler's per-column classification
            ("numeric" / "categorical" / "date"). Imputation strategy is
            chosen from this rather than from the pandas dtype, so the
            whole engine agrees on what a column *is* - see
            `_common.numeric_columns` for why that distinction matters.
        config: explicit cleaning choices; defaults if omitted.
    """
    config = config or CleaningConfig()
    cleaned = df.copy()

    rows_before = int(len(cleaned))
    missing_before = int(cleaned.isna().sum().sum())
    duplicates_before = int(cleaned.duplicated().sum())

    # Deduplication runs BEFORE imputation, deliberately. Doing it the
    # other way round is subtly destructive, and the first smoke test of
    # this module demonstrated it: a row that was entirely missing got
    # median/mode-imputed into an exact copy of a real row, and was then
    # deleted as a "duplicate" - so a genuine observation disappeared
    # because of a value the engine had invented moments earlier. It
    # also made the report self-contradictory (duplicates_before: 1,
    # duplicates_removed: 2), which would read as a bug to any user
    # comparing it against the duplicate count profiling already showed
    # them. Deduplicating the raw data first means only genuinely
    # identical *source* rows are ever removed, and the count the user
    # sees here matches the one from profiling.
    duplicates_removed = 0
    if config.duplicate_strategy == "remove" and duplicates_before > 0:
        cleaned = cleaned.drop_duplicates().reset_index(drop=True)
        duplicates_removed = rows_before - int(len(cleaned))

    column_actions: list[dict[str, Any]] = []

    for column in cleaned.columns:
        classification = classifications.get(column, "categorical")
        missing_in_column = int(cleaned[column].isna().sum())
        if missing_in_column == 0:
            continue

        action = _impute_column(cleaned, column, classification, config)
        action["column"] = column
        action["missing_before"] = missing_in_column
        action["missing_after"] = int(cleaned[column].isna().sum())
        action["values_changed"] = missing_in_column - action["missing_after"]
        column_actions.append(action)

    report: dict[str, Any] = {
        "config": config.to_dict(),
        "rows_before": rows_before,
        "rows_after": int(len(cleaned)),
        "rows_removed": rows_before - int(len(cleaned)),
        "missing_before": missing_before,
        "missing_after": int(cleaned.isna().sum().sum()),
        "missing_values_imputed": sum(a["values_changed"] for a in column_actions),
        "duplicates_before": duplicates_before,
        # Measured after imputation, so this can legitimately exceed
        # zero even when duplicates were removed: imputing missing
        # values can make two previously-distinct rows identical. That
        # is surfaced rather than hidden, precisely because those rows
        # are NOT deleted (see the ordering note above) - the user can
        # see it happened and decide for themselves.
        "duplicates_after": int(cleaned.duplicated().sum()),
        "duplicates_removed": duplicates_removed,
        "column_actions": column_actions,
    }
    return cleaned, report


def _impute_column(
    df: pd.DataFrame,
    column: str,
    classification: str,
    config: CleaningConfig,
) -> dict[str, Any]:
    """Fill one column in place on the already-copied frame."""
    if classification == "numeric" and config.numeric_strategy == "median":
        median = df[column].median()
        if pd.isna(median):
            # Every value in the column is missing - there is no median
            # to impute with. Leaving it untouched and saying so is the
            # only honest option; inventing a 0 would fabricate data.
            return {"action": "left_unchanged", "reason": "no_non_missing_values"}
        df[column] = df[column].fillna(median)
        return {"action": "imputed", "method": "median", "fill_value": safe_float(median)}

    if classification != "numeric" and config.categorical_strategy == "mode":
        modes = df[column].mode(dropna=True)
        if modes.empty:
            return {"action": "left_unchanged", "reason": "no_non_missing_values"}
        # .mode() returns every tied value; taking the first is the
        # conventional deterministic choice (pandas sorts them).
        fill_value = modes.iloc[0]
        df[column] = df[column].fillna(fill_value)
        return {"action": "imputed", "method": "mode", "fill_value": str(fill_value)}

    return {"action": "left_unchanged", "reason": "strategy_unchanged"}
