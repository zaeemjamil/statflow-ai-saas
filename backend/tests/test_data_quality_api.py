"""Stage 3 - data-correctness findings through real HTTP requests: they are
returned by the upload, persisted with the profile, and the analysis that
re-reads the stored file agrees with what the upload profiled."""

from __future__ import annotations

import io
from typing import Any

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

PROJECTS_URL = "/api/v1/projects"


def _project(client: TestClient, email: str) -> str:
    response = client.post(
        "/api/v1/auth/register", json={"email": email, "password": "correct-horse-1"}
    )
    assert response.status_code == 201, response.text
    created = client.post(PROJECTS_URL, json={"name": "DQ"})
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _upload(client: TestClient, project_id: str, name: str, content: bytes) -> Any:
    return client.post(
        f"{PROJECTS_URL}/{project_id}/upload", files={"file": (name, content, "text/plain")}
    )


def _notes(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {n["code"]: n for n in profile["import_notes"]}


def _messy_csv() -> bytes:
    n = 40
    frame = pd.DataFrame(
        {
            "row_id": range(1, n + 1),
            "score": [str(i) if i % 7 else "NA" for i in range(n)],
            "country": ["NA" if i % 5 == 0 else "US" for i in range(n)],
            "price": [f"${i * 10 + 1:,}" for i in range(n)],
            "share": [f"{i % 100}%" for i in range(n)],
            "when": ["03/04/2024", "05/06/2024", "01/02/2024", "07/08/2024"] * (n // 4),
            "measure": np.arange(n) * 1.5,
        }
    )
    return frame.to_csv(index=False).encode()


def test_upload_returns_every_finding_and_changes_no_value(client: TestClient) -> None:
    pid = _project(client, "dq1@example.com")
    response = _upload(client, pid, "messy.csv", _messy_csv())
    assert response.status_code == 201, response.text
    profile = response.json()["profile"]
    notes = _notes(profile)

    assert {
        "na_text_read_as_missing",
        "na_text_kept_as_value",
        "likely_identifier_columns",
        "formatted_numbers_as_text",
        "ambiguous_dates",
    } <= set(notes)
    assert notes["na_text_read_as_missing"]["columns"] == ["score"]
    assert notes["na_text_kept_as_value"]["columns"] == ["country"]
    assert "row_id" in notes["likely_identifier_columns"]["columns"]
    assert "price" not in notes["likely_identifier_columns"]["columns"]
    assert notes["formatted_numbers_as_text"]["columns"] == ["price", "share"]
    assert notes["ambiguous_dates"]["columns"] == ["when"]

    columns = {c["name"]: c for c in profile["columns"]}
    assert columns["score"]["classification"] == "numeric"
    assert columns["score"]["missing_count"] == 6  # i % 7 == 0 -> "NA": 0,7,14,21,28,35
    assert columns["country"]["missing_count"] == 0
    assert columns["price"]["classification"] == "categorical"  # not silently converted
    assert columns["row_id"]["classification"] == "numeric"  # flagged, not dropped
    assert profile["column_count"] == 7


def test_notes_survive_a_reload_via_profile_endpoint(client: TestClient) -> None:
    pid = _project(client, "dq2@example.com")
    uploaded = _upload(client, pid, "messy.csv", _messy_csv()).json()["profile"]
    fetched = client.get(f"{PROJECTS_URL}/{pid}/profile")
    assert fetched.status_code == 200
    assert fetched.json()["import_notes"] == uploaded["import_notes"]


def test_clean_file_has_no_notes(client: TestClient) -> None:
    pid = _project(client, "dq3@example.com")
    csv = pd.DataFrame({"a": [1.5, 2.5, 3.5], "b": ["x", "y", "x"]}).to_csv(index=False).encode()
    response = _upload(client, pid, "clean.csv", csv)
    assert response.status_code == 201
    assert response.json()["profile"]["import_notes"] == []


def test_xlsx_with_extra_sheets_warns_through_the_api(client: TestClient) -> None:
    pid = _project(client, "dq4@example.com")
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame({"a": [1, 2, 3]}).to_excel(writer, sheet_name="Data", index=False)
        pd.DataFrame({"b": [4]}).to_excel(writer, sheet_name="Notes", index=False)
    response = _upload(client, pid, "book.xlsx", buf.getvalue())
    assert response.status_code == 201, response.text
    note = _notes(response.json()["profile"])["xlsx_extra_sheets"]
    assert note["details"] == {"analysed_sheet": "Data", "ignored_sheets": ["Notes"]}


def test_duplicate_headers_warn_through_the_api(client: TestClient) -> None:
    pid = _project(client, "dq5@example.com")
    response = _upload(client, pid, "dup.csv", b"a,a,\n1,2,3\n4,5,6\n")
    assert response.status_code == 201, response.text
    assert {"duplicate_headers", "blank_headers"} <= set(_notes(response.json()["profile"]))


def test_analysis_after_reread_matches_the_upload_profile(client: TestClient) -> None:
    """The stored file is re-parsed for analysis; 'NA' handling must agree
    with what the upload profiled, or classifications would not match data."""
    pid = _project(client, "dq6@example.com")
    uploaded = _upload(client, pid, "messy.csv", _messy_csv()).json()["profile"]

    analysed = client.post(f"{PROJECTS_URL}/{pid}/analyze")
    assert analysed.status_code == 200, analysed.text
    body = analysed.json()
    assert body["status"] == "completed"
    # The six "NA" cells are missing values the cleaning step reports and imputes;
    # the text-kept "country" column has none (its "NA" cells are real values).
    actions = {a["column"]: a for a in body["cleaning"]["column_actions"]}
    assert actions["score"]["missing_before"] == 6
    assert "country" not in actions
    assert body["profile"]["columns"] == uploaded["columns"]
    # cleaned profile has no Stage 3 keys (it is the old shape)
    assert (
        "import_notes" not in body["cleaned_profile"]
        or body["cleaned_profile"]["import_notes"] == []
    )
