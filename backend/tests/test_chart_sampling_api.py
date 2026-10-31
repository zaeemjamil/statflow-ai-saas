"""
V1 hardening, Stage 2 - chart payload reduction through the real API.

The sampling rules themselves are pinned in test_chart_sampling.py. These
tests check the wiring: what the analysis endpoints return, what is stored,
and that nothing about the reported statistics changes. The limit is lowered
with monkeypatch so a few hundred rows exercise the same code path that
100,000 rows do in production.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import visualization
from app.models import Visualization
from tests.analytics_fixtures import regression_dataset

PROJECTS = "/api/v1/projects"
ROWS = 400
LIMIT = 50


def _register(client: TestClient, email: str) -> None:
    response = client.post(
        "/api/v1/auth/register", json={"email": email, "password": "correct-horse-1"}
    )
    assert response.status_code == 201, response.text


def _frame() -> pd.DataFrame:
    df = regression_dataset(n=ROWS, noise=2.0)
    df["captured_on"] = (
        pd.Timestamp("2026-02-01") + pd.to_timedelta(range(ROWS), unit="h")
    ).astype(str)
    df["region"] = ["north", "south", "east", "west"] * (ROWS // 4)
    return df


def _project_with_upload(client: TestClient, df: pd.DataFrame) -> str:
    response = client.post(PROJECTS, json={"name": "Sampling"})
    assert response.status_code == 201, response.text
    project_id = str(response.json()["id"])
    upload = client.post(
        f"{PROJECTS}/{project_id}/upload",
        files={"file": ("data.csv", df.to_csv(index=False).encode())},
    )
    assert upload.status_code == 201, upload.text
    return project_id


def _per_row(charts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [c for c in charts if c["chart_type"] in ("scatter", "line")]


def test_analysis_returns_bounded_charts_and_exact_statistics(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(visualization, "MAX_CHART_POINTS", LIMIT)
    _register(client, "sampling-a@example.com")
    df = _frame()
    project_id = _project_with_upload(client, df)

    body = client.post(f"{PROJECTS}/{project_id}/analyze").json()

    per_row = _per_row(body["visualizations"]["charts"])
    assert {c["chart_type"] for c in per_row} == {"scatter", "line"}
    for chart in per_row:
        assert len(chart["data"]) <= LIMIT
        assert chart["sampling"]["total_points"] == ROWS
        assert chart["sampling"]["displayed_points"] == len(chart["data"])
        assert chart["sampling"]["max_points"] == LIMIT

    # The reported statistic is the exact full-data value, not a sample's.
    column = next(c for c in body["statistics"]["columns"] if c["column"] == "driver_a")
    assert column["mean"] == pytest.approx(float(df["driver_a"].mean()), abs=1e-9)
    assert column["count"] == ROWS


def test_every_endpoint_that_returns_charts_is_bounded(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(visualization, "MAX_CHART_POINTS", LIMIT)
    _register(client, "sampling-b@example.com")
    project_id = _project_with_upload(client, _frame())
    client.post(f"{PROJECTS}/{project_id}/analyze")

    from_analysis = client.get(f"{PROJECTS}/{project_id}/analysis").json()["visualizations"]
    from_charts = client.get(f"{PROJECTS}/{project_id}/charts").json()
    regression = client.post(
        f"{PROJECTS}/{project_id}/regression",
        json={"target": "target", "predictors": ["driver_a", "driver_b"]},
    )
    assert regression.status_code == 200, regression.text

    for charts in (
        from_analysis["charts"],
        from_charts["charts"],
        regression.json()["visualizations"]["charts"],
    ):
        assert all(len(c["data"]) <= LIMIT for c in _per_row(charts))


def test_small_datasets_return_every_point_and_no_sampling_field_value(
    client: TestClient,
) -> None:
    _register(client, "sampling-c@example.com")
    project_id = _project_with_upload(client, _frame())

    charts = client.post(f"{PROJECTS}/{project_id}/analyze").json()["visualizations"]["charts"]

    for chart in _per_row(charts):
        assert len(chart["data"]) == ROWS  # 400 rows is far below the real 2,500 limit
        assert chart.get("sampling") is None


def test_an_analysis_stored_before_sampling_existed_is_bounded_when_read(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulates a pre-Stage-2 row: full-size data, no sampling metadata."""
    _register(client, "sampling-d@example.com")
    project_id = _project_with_upload(client, _frame())
    client.post(f"{PROJECTS}/{project_id}/analyze")  # real limit: stored unsampled (400 rows)

    stored = db_session.scalars(
        select(Visualization).where(Visualization.chart_type == "scatter")
    ).first()
    assert stored is not None and len(stored.config["data"]) == ROWS
    assert "sampling" not in stored.config

    monkeypatch.setattr(visualization, "MAX_CHART_POINTS", LIMIT)  # limit applied on read
    charts = client.get(f"{PROJECTS}/{project_id}/charts").json()["charts"]

    scatter = next(c for c in charts if c["chart_type"] == "scatter")
    assert len(scatter["data"]) <= LIMIT
    assert scatter["sampling"]["total_points"] == ROWS
    # Reading must not rewrite what is stored.
    db_session.expire_all()
    unchanged = db_session.get(Visualization, stored.id)
    assert unchanged is not None and len(unchanged.config["data"]) == ROWS
