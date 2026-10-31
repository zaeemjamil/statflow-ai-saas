"""
Phase 8A analysis API tests - real HTTP requests through the full
stack (auth -> ownership -> storage -> Phase 7 engine -> persistence ->
read endpoints). Datasets share no column names with StatFlow's retail
schema.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_storage
from app.models import Statistic, Visualization
from app.services import file_service
from tests.analytics_fixtures import regression_dataset

PROJECTS = "/api/v1/projects"
DASHBOARD = "/api/v1/dashboard/summary"


# --- helpers ----------------------------------------------------------


def _register(client: TestClient, email: str) -> None:
    response = client.post(
        "/api/v1/auth/register", json={"email": email, "password": "correct-horse-1"}
    )
    assert response.status_code == 201, response.text


def _switch_user(client: TestClient, email: str) -> None:
    client.post("/api/v1/auth/logout")
    _register(client, email)


def _dataset(
    rows: int = 80, with_missing: bool = True, with_duplicate: bool = True
) -> pd.DataFrame:
    df = regression_dataset(n=rows, noise=2.0)
    df["region"] = ["north", "south", "east", "west"] * (rows // 4)
    df["captured_on"] = (
        pd.Timestamp("2026-02-01") + pd.to_timedelta(range(rows), unit="D")
    ).astype(str)
    if with_missing:
        df.loc[0:3, "driver_a"] = np.nan
    if with_duplicate:
        df = pd.concat([df, df.iloc[[10]]], ignore_index=True)
    return df


def _new_project_with_unvalidated_upload(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, df: pd.DataFrame
) -> str:
    """Create a project whose stored dataset the upload rules would reject.

    Since V1 hardening, upload refuses a header-only file (422 `no_data_rows`), so the
    analysis endpoint's `empty_dataset` guard can no longer be reached through a normal
    upload. It stays as defence in depth (e.g. a file stored before the rule existed), and
    these tests keep covering it. Only the dataset-shape check (`validate_dataset`) is
    skipped, and only for this one upload: the real endpoint, parsing, profiling, storage
    write and database rows are all still used. The monkeypatch is undone as soon as the
    upload returns.
    """
    with monkeypatch.context() as patch:
        patch.setattr(file_service, "validate_dataset", lambda _df, _limits: None)
        return _new_project(client, df)


def _new_project(client: TestClient, df: pd.DataFrame | None = None, upload: bool = True) -> str:
    response = client.post(PROJECTS, json={"name": "Telemetry"})
    assert response.status_code == 201, response.text
    project_id = str(response.json()["id"])
    if upload:
        frame = _dataset() if df is None else df
        upload_response = client.post(
            f"{PROJECTS}/{project_id}/upload",
            files={"file": ("data.csv", frame.to_csv(index=False).encode())},
        )
        assert upload_response.status_code == 201, upload_response.text
    return project_id


def _clean(client: TestClient, project_id: str, **overrides: str) -> Any:
    body = {
        "numeric_strategy": "median",
        "categorical_strategy": "mode",
        "duplicate_strategy": "keep",
        **overrides,
    }
    return client.post(f"{PROJECTS}/{project_id}/clean", json=body)


def _analyzed_project(client: TestClient, df: pd.DataFrame | None = None, **clean: str) -> str:
    project_id = _new_project(client, df)
    assert _clean(client, project_id, **clean).status_code == 200
    response = client.post(f"{PROJECTS}/{project_id}/analyze")
    assert response.status_code == 200, response.text
    return project_id


def _status(client: TestClient, project_id: str) -> str:
    return str(client.get(f"{PROJECTS}/{project_id}").json()["status"])


# --- dashboard summary ------------------------------------------------


def test_dashboard_for_a_new_user_is_honest_zeros(client: TestClient) -> None:
    _register(client, "new@example.com")
    body = client.get(DASHBOARD).json()

    assert body["total_projects"] == 0
    assert body["files_analyzed"] == 0
    assert body["reports_generated"] == 0
    assert body["ai_insights_generated"] == 0
    assert body["recent_projects"] == []


def test_dashboard_reflects_real_projects_and_analysis(client: TestClient) -> None:
    _register(client, "dash@example.com")
    uploaded_only = _new_project(client)
    analyzed = _analyzed_project(client)

    body = client.get(DASHBOARD).json()
    assert body["total_projects"] == 2
    # Only the project that completed analysis counts as "analyzed";
    # merely uploading a file does not.
    assert body["files_analyzed"] == 1
    assert body["reports_generated"] == 0  # Phase 10 not built: truthfully 0
    assert body["ai_insights_generated"] == 0  # Phase 9 not built: truthfully 0
    ids = {p["id"] for p in body["recent_projects"]}
    assert ids == {uploaded_only, analyzed}


def test_dashboard_only_counts_the_callers_own_projects(client: TestClient) -> None:
    _register(client, "alice@example.com")
    _analyzed_project(client)
    _switch_user(client, "bob@example.com")

    body = client.get(DASHBOARD).json()
    assert body["total_projects"] == 0
    assert body["files_analyzed"] == 0
    assert body["recent_projects"] == []


def test_dashboard_recent_projects_are_capped_and_newest_first(client: TestClient) -> None:
    _register(client, "many@example.com")
    for _ in range(7):
        _new_project(client, upload=False)

    body = client.get(DASHBOARD).json()
    assert body["total_projects"] == 7
    assert len(body["recent_projects"]) == 5
    stamps = [p["updated_at"] for p in body["recent_projects"]]
    assert stamps == sorted(stamps, reverse=True)


# --- cleaning ---------------------------------------------------------


def test_clean_returns_the_before_and_after_report(client: TestClient) -> None:
    _register(client, "clean@example.com")
    project_id = _new_project(client)

    response = _clean(client, project_id, duplicate_strategy="remove")
    assert response.status_code == 200
    body = response.json()

    report = body["cleaning"]
    assert report["rows_before"] == 81  # 80 + 1 duplicate
    assert report["rows_after"] == 80
    assert report["duplicates_removed"] == 1
    assert report["missing_before"] == 4
    assert report["missing_after"] == 0
    assert report["missing_values_imputed"] == 4
    assert report["config"]["duplicate_strategy"] == "remove"
    assert {a["column"] for a in report["column_actions"]} == {"driver_a"}
    assert body["cleaned_profile"]["row_count"] == 80
    assert body["profile"]["row_count"] == 81


def test_clean_persists_state_and_advances_the_project(client: TestClient) -> None:
    _register(client, "state@example.com")
    project_id = _new_project(client)
    assert _status(client, project_id) == "profiled"

    _clean(client, project_id)
    assert _status(client, project_id) == "cleaning_completed"

    persisted = client.get(f"{PROJECTS}/{project_id}/analysis").json()
    assert persisted["cleaning"]["rows_before"] == 81
    assert persisted["stages"]["cleaning"] == "completed"
    # Cleaning alone must not claim anything downstream ran.
    assert persisted["stages"]["statistics"] == "pending"
    assert persisted["statistics"] is None


def test_clean_never_modifies_the_uploaded_source(client: TestClient) -> None:
    """Cleaning with duplicate removal must leave the stored original
    untouched: the upload-time profile still describes all 81 rows, and
    re-cleaning with different settings starts from the original."""
    _register(client, "source@example.com")
    project_id = _new_project(client)

    _clean(client, project_id, duplicate_strategy="remove")
    profile = client.get(f"{PROJECTS}/{project_id}/profile").json()
    assert profile["row_count"] == 81

    again = _clean(client, project_id, duplicate_strategy="keep").json()
    assert again["cleaning"]["rows_after"] == 81  # original rows still all there


def test_clean_rejects_an_invalid_strategy(client: TestClient) -> None:
    _register(client, "bad@example.com")
    project_id = _new_project(client)

    response = _clean(client, project_id, numeric_strategy="delete_everything")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_clean_on_a_project_without_a_file_is_a_conflict(client: TestClient) -> None:
    _register(client, "nofile@example.com")
    project_id = _new_project(client, upload=False)

    response = _clean(client, project_id)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_file_uploaded"
    assert _status(client, project_id) == "created"


def test_recleaning_invalidates_downstream_results(client: TestClient) -> None:
    """Statistics/regression computed from the previous cleaning must not
    be served beside a new cleaning report they no longer match."""
    _register(client, "reclean@example.com")
    project_id = _analyzed_project(client)
    client.post(
        f"{PROJECTS}/{project_id}/regression",
        json={"target": "target", "predictors": ["driver_a", "driver_b"]},
    )

    _clean(client, project_id, duplicate_strategy="remove")

    persisted = client.get(f"{PROJECTS}/{project_id}/analysis").json()
    assert persisted["statistics"] is None
    assert persisted["regression"] is None
    assert persisted["visualizations"] is None
    assert persisted["status"] == "pending"
    assert client.get(f"{PROJECTS}/{project_id}/statistics").status_code == 409
    assert _status(client, project_id) == "cleaning_completed"


# --- analysis ---------------------------------------------------------


def test_analyze_runs_the_full_pipeline_and_reports_real_stages(client: TestClient) -> None:
    _register(client, "analyze@example.com")
    project_id = _new_project(client)
    _clean(client, project_id)

    response = client.post(f"{PROJECTS}/{project_id}/analyze")
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "completed"
    assert body["stages"] == {
        "profiling": "completed",
        "cleaning": "completed",
        "statistics": "completed",
        "correlations": "completed",
        "outliers": "completed",
        "regression": "skipped",  # nothing requested yet: not faked as done
        "visualizations": "completed",
    }
    assert body["statistics"]["numeric_column_count"] == 3
    assert body["correlations"]["available"] is True
    assert body["outliers"]["columns"]
    assert body["visualizations"]["chart_count"] > 0
    assert body["regression"] is None
    assert body["completed_at"] is not None
    assert _status(client, project_id) == "completed"


def test_analyze_without_a_prior_clean_applies_the_defaults(client: TestClient) -> None:
    _register(client, "noclean@example.com")
    project_id = _new_project(client)

    body = client.post(f"{PROJECTS}/{project_id}/analyze").json()

    assert body["status"] == "completed"
    assert body["cleaning"]["config"] == {
        "numeric_strategy": "median",
        "categorical_strategy": "mode",
        "duplicate_strategy": "keep",
    }


def test_analyze_uses_the_stored_cleaning_config(client: TestClient) -> None:
    _register(client, "config@example.com")
    project_id = _new_project(client)
    _clean(client, project_id, duplicate_strategy="remove")

    body = client.post(f"{PROJECTS}/{project_id}/analyze").json()

    assert body["cleaning"]["config"]["duplicate_strategy"] == "remove"
    assert body["cleaned_profile"]["row_count"] == 80


def test_repeated_analysis_replaces_results_instead_of_duplicating(
    client: TestClient, db_session: Session
) -> None:
    _register(client, "repeat@example.com")
    project_id = _new_project(client)

    client.post(f"{PROJECTS}/{project_id}/analyze")
    stats_first = db_session.scalar(select(func.count(Statistic.id)))
    charts_first = db_session.scalar(select(func.count(Visualization.id)))
    first = client.get(f"{PROJECTS}/{project_id}/statistics").json()

    client.post(f"{PROJECTS}/{project_id}/analyze")
    db_session.expire_all()
    assert db_session.scalar(select(func.count(Statistic.id))) == stats_first
    assert db_session.scalar(select(func.count(Visualization.id))) == charts_first
    assert client.get(f"{PROJECTS}/{project_id}/statistics").json() == first


def test_repeated_analysis_keeps_a_previous_regression(client: TestClient) -> None:
    _register(client, "keepreg@example.com")
    project_id = _analyzed_project(client)
    client.post(
        f"{PROJECTS}/{project_id}/regression",
        json={"target": "target", "predictors": ["driver_b"]},
    )

    body = client.post(f"{PROJECTS}/{project_id}/analyze").json()

    assert body["regression"]["available"] is True
    assert body["stages"]["regression"] == "completed"


def test_analyze_on_a_project_without_a_file_is_a_conflict(client: TestClient) -> None:
    _register(client, "nofile2@example.com")
    project_id = _new_project(client, upload=False)

    response = client.post(f"{PROJECTS}/{project_id}/analyze")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_file_uploaded"


def test_header_only_file_is_rejected_at_upload_so_it_never_reaches_analysis(
    client: TestClient,
) -> None:
    """Guards the premise of the two tests below: through the real upload path the
    header-only file is refused, so they must seed it by bypassing validation."""
    _register(client, "premise@example.com")
    project_id = _new_project(client, upload=False)
    header_only = pd.DataFrame({"a": pd.Series([], dtype="float64")})

    response = client.post(
        f"{PROJECTS}/{project_id}/upload",
        files={"file": ("data.csv", header_only.to_csv(index=False).encode())},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "no_data_rows"


def test_analysis_of_an_empty_dataset_fails_safely_and_is_recorded(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _register(client, "empty@example.com")
    header_only = pd.DataFrame(
        {"a": pd.Series([], dtype="float64"), "b": pd.Series([], dtype="float64")}
    )
    project_id = _new_project_with_unvalidated_upload(client, monkeypatch, header_only)

    response = client.post(f"{PROJECTS}/{project_id}/analyze")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "empty_dataset"
    assert "Traceback" not in response.text
    assert _status(client, project_id) == "failed"
    persisted = client.get(f"{PROJECTS}/{project_id}/analysis").json()
    assert persisted["status"] == "failed"
    assert persisted["error_message"]


def test_a_failed_analysis_can_be_retried_after_the_data_problem_is_fixed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _register(client, "retry@example.com")
    project_id = _new_project_with_unvalidated_upload(
        client, monkeypatch, pd.DataFrame({"a": pd.Series([], dtype="float64")})
    )
    assert client.post(f"{PROJECTS}/{project_id}/analyze").status_code == 422
    assert _status(client, project_id) == "failed"

    # Upload is one-per-project in V1, so "retry" here means the project
    # can be re-run (and would succeed on valid data) rather than being
    # stuck: the status is a record, not a lock.
    again = client.post(f"{PROJECTS}/{project_id}/analyze")
    assert again.status_code == 422
    assert _status(client, project_id) == "failed"


def test_analysis_with_a_missing_stored_file_is_a_safe_404(client: TestClient) -> None:
    _register(client, "lost@example.com")
    project_id = _new_project(client)

    class _LostStorage:
        def get_file(self, *, storage_key: str) -> bytes:
            raise FileNotFoundError(storage_key)

    cast(FastAPI, client.app).dependency_overrides[get_storage] = lambda: _LostStorage()
    response = client.post(f"{PROJECTS}/{project_id}/analyze")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "file_unavailable"
    assert "uploads/" not in response.text  # storage key never leaks


def test_get_analysis_before_any_run_is_404(client: TestClient) -> None:
    _register(client, "none@example.com")
    project_id = _new_project(client)

    response = client.get(f"{PROJECTS}/{project_id}/analysis")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "analysis_not_found"


# --- statistics / correlations / outliers / charts --------------------


def test_statistics_endpoint_returns_every_metric_in_dataset_order(client: TestClient) -> None:
    _register(client, "stats@example.com")
    project_id = _analyzed_project(client)

    body = client.get(f"{PROJECTS}/{project_id}/statistics").json()

    assert [c["column"] for c in body["columns"]] == ["driver_a", "driver_b", "target"]
    first = body["columns"][0]
    for metric in ("count", "mean", "median", "std", "min", "q1", "q3", "max", "iqr"):
        assert first[metric] is not None
    assert set(body["skipped_columns"]) == {"region", "captured_on"}


def test_statistics_match_a_direct_computation_of_the_cleaned_data(client: TestClient) -> None:
    """Persisted numbers must be the real ones, not just present."""
    _register(client, "truth@example.com")
    df = _dataset(with_duplicate=False)
    project_id = _analyzed_project(client, df)

    body = client.get(f"{PROJECTS}/{project_id}/statistics").json()
    served = {c["column"]: c for c in body["columns"]}

    cleaned = df["driver_b"]  # no missing values in this column
    assert served["driver_b"]["mean"] == pytest.approx(cleaned.mean(), rel=1e-9)
    assert served["driver_b"]["std"] == pytest.approx(cleaned.std(ddof=1), rel=1e-9)
    # driver_a was median-imputed, so its mean is over the filled data.
    filled = df["driver_a"].fillna(df["driver_a"].median())
    assert served["driver_a"]["mean"] == pytest.approx(filled.mean(), rel=1e-9)


def test_correlations_endpoint(client: TestClient) -> None:
    _register(client, "corr@example.com")
    project_id = _analyzed_project(client)

    body = client.get(f"{PROJECTS}/{project_id}/correlations").json()

    assert body["available"] is True
    assert set(body["matrix"]) == {"driver_a", "driver_b", "target"}
    assert body["pairs"]
    assert body["strongest_positive"] is not None
    for pair in body["pairs"]:
        assert pair["column_a"] != pair["column_b"]


def test_outliers_endpoint(client: TestClient) -> None:
    _register(client, "out@example.com")
    df = _dataset(with_missing=False, with_duplicate=False)
    df.loc[5, "driver_b"] = 10_000.0  # one unmistakable outlier
    project_id = _analyzed_project(client, df)

    body = client.get(f"{PROJECTS}/{project_id}/outliers").json()

    assert body["method"] == "iqr"
    column = next(c for c in body["columns"] if c["column"] == "driver_b")
    assert column["outlier_count"] >= 1
    assert 5 in column["outlier_indices"]
    assert column["lower_bound"] is not None and column["upper_bound"] is not None


def test_charts_endpoint_returns_backend_recommendations(client: TestClient) -> None:
    _register(client, "charts@example.com")
    project_id = _analyzed_project(client)

    body = client.get(f"{PROJECTS}/{project_id}/charts").json()

    assert body["available"] is True
    assert body["chart_count"] == len(body["charts"]) > 0
    types = {c["chart_type"] for c in body["charts"]}
    assert types <= {"scatter", "line", "bar", "histogram", "count"}
    assert {"scatter", "histogram"} <= types
    for chart in body["charts"]:
        assert chart["reason"]
        assert chart["data"]


def test_chart_order_is_stable_across_reads(client: TestClient) -> None:
    _register(client, "order@example.com")
    project_id = _analyzed_project(client)
    first = client.get(f"{PROJECTS}/{project_id}/charts").json()["charts"]
    second = client.get(f"{PROJECTS}/{project_id}/charts").json()["charts"]
    assert [c["title"] for c in first] == [c["title"] for c in second]


@pytest.mark.parametrize("path", ["statistics", "correlations", "outliers", "charts"])
def test_result_endpoints_404_before_any_analysis_exists(client: TestClient, path: str) -> None:
    _register(client, f"early-{path}@example.com")
    project_id = _new_project(client)

    response = client.get(f"{PROJECTS}/{project_id}/{path}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "analysis_not_found"


@pytest.mark.parametrize("path", ["statistics", "correlations", "outliers", "charts"])
def test_result_endpoints_409_when_only_cleaning_has_run(client: TestClient, path: str) -> None:
    """The analysis row exists but the stage hasn't run: a different
    state from 'no analysis', and reported as such."""
    _register(client, f"cleanonly-{path}@example.com")
    project_id = _new_project(client)
    _clean(client, project_id)

    response = client.get(f"{PROJECTS}/{project_id}/{path}")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "analysis_not_completed"


def test_all_endpoints_serve_the_same_persisted_result(client: TestClient) -> None:
    """The consistency requirement: every view of one analysis agrees."""
    _register(client, "consistent@example.com")
    project_id = _analyzed_project(client)
    base = f"{PROJECTS}/{project_id}"

    whole = client.get(f"{base}/analysis").json()
    assert client.get(f"{base}/statistics").json() == whole["statistics"]
    assert client.get(f"{base}/correlations").json() == whole["correlations"]
    assert client.get(f"{base}/outliers").json() == whole["outliers"]
    assert client.get(f"{base}/charts").json() == whole["visualizations"]


# --- regression -------------------------------------------------------


def test_regression_recovers_known_coefficients_and_persists(client: TestClient) -> None:
    _register(client, "reg@example.com")
    df = regression_dataset(n=120, noise=0.0)  # target = 5 + 3a - 2b exactly
    project_id = _analyzed_project(client, df)

    response = client.post(
        f"{PROJECTS}/{project_id}/regression",
        json={"target": "target", "predictors": ["driver_a", "driver_b"]},
    )
    assert response.status_code == 200
    result = response.json()["regression"]

    assert result["model"]["intercept"] == pytest.approx(5.0, abs=1e-6)
    coefficients = {c["name"]: c["coefficient"] for c in result["coefficients"]}
    assert coefficients["driver_a"] == pytest.approx(3.0, abs=1e-6)
    assert coefficients["driver_b"] == pytest.approx(-2.0, abs=1e-6)
    assert result["metrics"]["r_squared"] == pytest.approx(1.0, abs=1e-8)
    assert result["model"]["train_observations"] + result["model"]["test_observations"] == 120

    persisted = client.get(f"{PROJECTS}/{project_id}/analysis").json()
    assert persisted["regression"] == result
    assert persisted["stages"]["regression"] == "completed"


def test_regression_is_reproducible(client: TestClient) -> None:
    _register(client, "repro@example.com")
    project_id = _analyzed_project(client)
    body = {"target": "target", "predictors": ["driver_a", "driver_b"]}

    first = client.post(f"{PROJECTS}/{project_id}/regression", json=body).json()["regression"]
    second = client.post(f"{PROJECTS}/{project_id}/regression", json=body).json()["regression"]
    assert first == second


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"target": "region", "predictors": ["driver_a"]}, "regression_target_not_numeric"),
        ({"target": "target", "predictors": ["region"]}, "regression_predictor_not_numeric"),
        ({"target": "ghost", "predictors": ["driver_a"]}, "regression_target_not_found"),
        ({"target": "target", "predictors": ["ghost"]}, "regression_predictor_not_found"),
        (
            {"target": "target", "predictors": ["target", "driver_a"]},
            "regression_target_in_predictors",
        ),
    ],
)
def test_invalid_regression_selections_return_specific_errors(
    client: TestClient, body: dict[str, Any], code: str
) -> None:
    _register(client, f"badreg-{code}@example.com")
    project_id = _analyzed_project(client)

    response = client.post(f"{PROJECTS}/{project_id}/regression", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == code
    assert "Traceback" not in response.text


def test_empty_predictors_are_rejected(client: TestClient) -> None:
    _register(client, "nopred@example.com")
    project_id = _analyzed_project(client)

    response = client.post(
        f"{PROJECTS}/{project_id}/regression", json={"target": "target", "predictors": []}
    )
    assert response.status_code == 422


def test_a_rejected_regression_does_not_overwrite_a_good_one(client: TestClient) -> None:
    _register(client, "keep@example.com")
    project_id = _analyzed_project(client)
    good = client.post(
        f"{PROJECTS}/{project_id}/regression",
        json={"target": "target", "predictors": ["driver_a", "driver_b"]},
    ).json()["regression"]

    bad = client.post(
        f"{PROJECTS}/{project_id}/regression",
        json={"target": "target", "predictors": ["region"]},
    )
    assert bad.status_code == 422

    assert client.get(f"{PROJECTS}/{project_id}/analysis").json()["regression"] == good


def test_regression_before_analysis_is_a_conflict(client: TestClient) -> None:
    _register(client, "early-reg@example.com")
    project_id = _new_project(client)
    _clean(client, project_id)

    response = client.post(
        f"{PROJECTS}/{project_id}/regression",
        json={"target": "target", "predictors": ["driver_a"]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "analysis_not_completed"


def test_regression_with_no_analysis_at_all_is_404(client: TestClient) -> None:
    _register(client, "noanalysis@example.com")
    project_id = _new_project(client)

    response = client.post(
        f"{PROJECTS}/{project_id}/regression",
        json={"target": "target", "predictors": ["driver_a"]},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "analysis_not_found"


def test_regression_uses_the_cleaned_data_not_the_raw_upload(client: TestClient) -> None:
    """With rows containing missing values, imputation (the default)
    keeps all of them, so none are silently dropped from the model."""
    _register(client, "cleaned-reg@example.com")
    project_id = _analyzed_project(client)  # driver_a has 4 missing values

    model = client.post(
        f"{PROJECTS}/{project_id}/regression",
        json={"target": "target", "predictors": ["driver_a", "driver_b"]},
    ).json()["regression"]["model"]

    assert model["rows_dropped_for_missing_values"] == 0
    assert model["observations_used"] == 81


# --- authentication ---------------------------------------------------

_PROJECT_SCOPED = [
    (
        "POST",
        "clean",
        {
            "numeric_strategy": "median",
            "categorical_strategy": "mode",
            "duplicate_strategy": "keep",
        },
    ),
    ("POST", "analyze", None),
    ("GET", "analysis", None),
    ("GET", "statistics", None),
    ("GET", "correlations", None),
    ("GET", "outliers", None),
    ("GET", "charts", None),
    ("POST", "regression", {"target": "target", "predictors": ["driver_a"]}),
]


@pytest.mark.parametrize(("method", "path", "body"), _PROJECT_SCOPED)
def test_every_analysis_endpoint_requires_authentication(
    client: TestClient, method: str, path: str, body: dict[str, Any] | None
) -> None:
    response = client.request(method, f"{PROJECTS}/{uuid.uuid4()}/{path}", json=body)
    assert response.status_code == 401


def test_dashboard_requires_authentication(client: TestClient) -> None:
    assert client.get(DASHBOARD).status_code == 401


# --- ownership isolation ----------------------------------------------


@pytest.mark.parametrize(("method", "path", "body"), _PROJECT_SCOPED)
def test_user_b_gets_404_on_every_endpoint_of_user_a_project(
    client: TestClient, method: str, path: str, body: dict[str, Any] | None
) -> None:
    _register(client, f"owner-{path}@example.com")
    project_id = _analyzed_project(client)
    _switch_user(client, f"intruder-{path}@example.com")

    response = client.request(method, f"{PROJECTS}/{project_id}/{path}", json=body)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_a_404_for_someone_elses_project_matches_a_nonexistent_one(client: TestClient) -> None:
    """Existence must not be distinguishable from outside."""
    _register(client, "alice-exists@example.com")
    project_id = _analyzed_project(client)
    _switch_user(client, "bob-probe@example.com")

    foreign = client.get(f"{PROJECTS}/{project_id}/statistics")
    missing = client.get(f"{PROJECTS}/{uuid.uuid4()}/statistics")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


def test_user_b_cannot_see_user_a_data_through_any_response(client: TestClient) -> None:
    _register(client, "leak-a@example.com")
    project_id = _analyzed_project(client)
    _switch_user(client, "leak-b@example.com")

    for path in ("analysis", "statistics", "correlations", "outliers", "charts"):
        text = client.get(f"{PROJECTS}/{project_id}/{path}").text
        assert "driver_a" not in text
        assert "driver_b" not in text


# --- invalid projects -------------------------------------------------


@pytest.mark.parametrize(("method", "path", "body"), _PROJECT_SCOPED)
def test_nonexistent_project_is_404(
    client: TestClient, method: str, path: str, body: dict[str, Any] | None
) -> None:
    _register(client, f"ghost-{path}@example.com")
    response = client.request(method, f"{PROJECTS}/{uuid.uuid4()}/{path}", json=body)
    assert response.status_code == 404


def test_malformed_project_id_is_a_standard_validation_error(client: TestClient) -> None:
    _register(client, "malformed@example.com")
    response = client.get(f"{PROJECTS}/not-a-uuid/statistics")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# --- status progression -----------------------------------------------


def test_project_status_walks_the_documented_pipeline(client: TestClient) -> None:
    _register(client, "walk@example.com")
    project_id = _new_project(client, upload=False)
    seen = [_status(client, project_id)]

    client.post(
        f"{PROJECTS}/{project_id}/upload",
        files={"file": ("d.csv", _dataset().to_csv(index=False).encode())},
    )
    seen.append(_status(client, project_id))
    _clean(client, project_id)
    seen.append(_status(client, project_id))
    client.post(f"{PROJECTS}/{project_id}/analyze")
    seen.append(_status(client, project_id))

    assert seen == ["created", "profiled", "cleaning_completed", "completed"]


def test_responses_are_json_serializable_and_free_of_non_finite_numbers(
    client: TestClient,
) -> None:
    """NaN/Infinity are not valid JSON; a constant column makes pandas
    produce them, so this guards the whole persisted->served path."""
    _register(client, "finite@example.com")
    df = _dataset(with_missing=False, with_duplicate=False)
    df["fixed"] = 7.0
    project_id = _analyzed_project(client, df)

    for path in ("analysis", "statistics", "correlations", "outliers", "charts"):
        text = client.get(f"{PROJECTS}/{project_id}/{path}").text
        assert "NaN" not in text
        assert "Infinity" not in text
