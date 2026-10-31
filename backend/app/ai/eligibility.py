"""
Eligibility: may this analysis be explained by the AI Analyst at all?

The AI must only ever describe results that really exist. These rules look at
the persisted analysis (the same ``AnalysisPublic`` the dashboard shows) and
give either "eligible" or one specific, plain-language reason why not. Nothing
here calls an AI, reads the database or reads the dataset.

Optional sections (correlations, outliers, regression, charts) never block
eligibility: a project with only descriptive statistics can still be
explained, and the evidence packet states honestly which sections are absent.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.exceptions import ConflictException
from app.schemas.analysis import AnalysisPublic

# Row policy (rows AFTER cleaning). Both numbers live here and nowhere else.
#
#   fewer than MIN_ROWS_FOR_EXPLANATION      -> refused (`too_few_rows`)
#   MIN_ROWS_FOR_EXPLANATION .. SMALL_SAMPLE_ROWS - 1
#                                            -> eligible, with a `small_sample` warning
#   SMALL_SAMPLE_ROWS or more                -> eligible, no warning from this rule
#
# The warning is a flag, not a finding. Reaching 30 rows does NOT make results
# reliable, and any explanation - at any row count - must avoid claims of
# statistical significance or causation that the evidence does not support.
MIN_ROWS_FOR_EXPLANATION = 5
SMALL_SAMPLE_ROWS = 30

# Reason codes. Stable strings: later stages and the UI may branch on them.
ANALYSIS_NOT_COMPLETED = "analysis_not_completed"
STATISTICS_NOT_COMPLETED = "statistics_not_completed"
NO_DATASET_PROFILE = "no_dataset_profile"
TOO_FEW_ROWS = "too_few_rows"
NO_NUMERIC_COLUMNS = "no_numeric_columns"
EVIDENCE_TOO_LARGE = "evidence_too_large"
ELIGIBLE = "eligible"

# Warning codes (machine-readable; carried on the result and in the packet).
SMALL_SAMPLE = "small_sample"


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    reason_code: str
    message: str
    # Only ever non-empty for an eligible result.
    warnings: tuple[str, ...] = ()


class EvidenceNotEligible(ConflictException):
    """Raised when evidence is requested for an analysis that cannot be
    explained. Carries the specific reason code (HTTP 409 if it ever reaches
    the API; no endpoint uses it in Stage 1)."""

    def __init__(self, result: EligibilityResult) -> None:
        super().__init__(result.message, error_code=result.reason_code)
        self.result = result


def _no(code: str, message: str) -> EligibilityResult:
    return EligibilityResult(eligible=False, reason_code=code, message=message)


def check_eligibility(analysis: AnalysisPublic) -> EligibilityResult:
    """Apply the rules in a fixed order; the first failing rule is reported."""
    if analysis.status != "completed":
        return _no(
            ANALYSIS_NOT_COMPLETED,
            "Run the analysis to completion before asking for an explanation.",
        )
    if analysis.stages.get("statistics") != "completed":
        return _no(
            STATISTICS_NOT_COMPLETED,
            "The statistics step has not completed, so there is nothing to explain yet.",
        )
    if analysis.profile is None:
        return _no(NO_DATASET_PROFILE, "This project has no dataset summary to explain.")

    # Cleaning may remove duplicate rows, so judge the data the statistics
    # were actually computed from.
    basis = analysis.cleaned_profile or analysis.profile
    if basis.row_count < MIN_ROWS_FOR_EXPLANATION:
        return _no(
            TOO_FEW_ROWS,
            f"This dataset has only {basis.row_count} row"
            f"{'' if basis.row_count == 1 else 's'} after cleaning; at least "
            f"{MIN_ROWS_FOR_EXPLANATION} are needed for a meaningful explanation.",
        )
    if analysis.statistics is None or not analysis.statistics.columns:
        return _no(
            NO_NUMERIC_COLUMNS,
            "This dataset has no numeric columns with statistics, so there is nothing to explain.",
        )
    warnings = (SMALL_SAMPLE,) if basis.row_count < SMALL_SAMPLE_ROWS else ()
    return EligibilityResult(True, ELIGIBLE, "This analysis can be explained.", warnings)
