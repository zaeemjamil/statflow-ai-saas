"""
Upload endpoint tests, via real HTTP requests (multipart file upload)
against the real parsing/profiling/storage pipeline - not a bypass of
it. Storage is isolated to a per-test temp directory (see conftest.py's
`client` fixture), so nothing here touches the real filesystem outside
the test's own lifetime.
"""

from __future__ import annotations

import io
from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import ValidationException
from app.models import FileType
from app.services import file_service

PROJECTS_URL = "/api/v1/projects"


def _register_and_login(client: TestClient, email: str, password: str = "correct-horse-1") -> None:
    response = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201, response.text


def _create_project(client: TestClient, name: str = "Q3 Sales") -> dict[str, Any]:
    response = client.post(PROJECTS_URL, json={"name": name})
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def _upload_url(project_id: str) -> str:
    return f"{PROJECTS_URL}/{project_id}/upload"


def _csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def _xlsx_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False, sheet_name="Sheet1")
    return buf.getvalue()


_SAMPLE_DF = pd.DataFrame({"revenue": [100.0, 250.5, 300.0], "region": ["East", "West", "East"]})


# --- valid uploads ------------------------------------------------------


def test_upload_valid_csv(client: TestClient) -> None:
    _register_and_login(client, "csv@example.com")
    project = _create_project(client)

    response = client.post(
        _upload_url(project["id"]),
        files={"file": ("sales.csv", _csv_bytes(_SAMPLE_DF), "text/csv")},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["file"]["original_filename"] == "sales.csv"
    assert body["file"]["file_type"] == "csv"
    assert body["profile"]["row_count"] == 3
    assert body["profile"]["column_count"] == 2
    assert body["profile"]["numeric_column_count"] == 1
    assert body["profile"]["categorical_column_count"] == 1
    # The server-generated storage path is never returned to the client.
    assert "storage_key" not in body["file"]


def test_upload_valid_xlsx(client: TestClient) -> None:
    _register_and_login(client, "xlsx@example.com")
    project = _create_project(client)

    response = client.post(
        _upload_url(project["id"]),
        files={
            "file": (
                "sales.xlsx",
                _xlsx_bytes(_SAMPLE_DF),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["file"]["file_type"] == "xlsx"
    assert body["profile"]["row_count"] == 3


def test_successful_upload_marks_the_project_profiled(client: TestClient) -> None:
    """Upload, parsing and profiling happen atomically in one request,
    so by the time the response returns the project is `profiled` - an
    intermediate persisted `uploaded` state would never be observable.
    (Phase 6 asserted `uploaded`; Phase 8A's finer-grained status model
    made `profiled` the truthful post-upload state.)"""
    _register_and_login(client, "status@example.com")
    project = _create_project(client)
    assert project["status"] == "created"

    client.post(_upload_url(project["id"]), files={"file": ("d.csv", _csv_bytes(_SAMPLE_DF))})

    updated = client.get(f"{PROJECTS_URL}/{project['id']}")
    assert updated.json()["status"] == "profiled"


# --- rejected uploads -----------------------------------------------------


def test_upload_unsupported_extension_is_rejected(client: TestClient) -> None:
    _register_and_login(client, "ext@example.com")
    project = _create_project(client)

    response = client.post(
        _upload_url(project["id"]), files={"file": ("data.txt", b"just some text", "text/plain")}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_file_type"


def test_upload_malformed_csv_is_rejected(client: TestClient) -> None:
    _register_and_login(client, "badcsv@example.com")
    project = _create_project(client)

    # A header promising 3 columns, then a data row with 6 fields - not
    # recoverable by any reasonable delimiter guess.
    malformed = b"a,b,c\n1,2,3,4,5,6\n"
    response = client.post(
        _upload_url(project["id"]), files={"file": ("bad.csv", malformed, "text/csv")}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unparseable_file"


def test_ragged_csv_is_never_silently_coerced_into_a_valid_dataframe() -> None:
    """Regression guard at the parser level.

    Before the fix, this exact input parsed "successfully" into a
    (1, 3) DataFrame whose values were wrong: pandas absorbed the three
    extra fields by promoting `1 2 3` into the row index. That produced
    a plausible-looking dataset with corrupted contents, which is far
    worse than a rejected upload - the user would have analyzed
    silently-wrong data.

    Asserted here rather than only through HTTP because the endpoint
    test above returns 422 either way, so it can't distinguish "rejected
    for the right reason" from "rejected by some other check".
    """
    with pytest.raises(ValidationException) as exc_info:
        file_service.parse_dataset(b"a,b,c\n1,2,3,4,5,6\n", FileType.CSV)
    assert exc_info.value.error_code == "unparseable_file"


def test_well_formed_csv_still_parses_after_the_strict_parsing_fix() -> None:
    """The strict-parsing settings must not make ordinary files fail -
    the counterpart to the regression test above."""
    df = file_service.parse_dataset(b"a,b,c\n1,2,3\n4,5,6\n", FileType.CSV)
    assert df.shape == (2, 3)
    assert list(df.columns) == ["a", "b", "c"]
    assert df["a"].tolist() == [1, 4]


def test_semicolon_delimited_csv_is_still_detected() -> None:
    """Delimiter sniffing must survive the strict-parsing change too."""
    df = file_service.parse_dataset(b"a;b;c\n1;2;3\n4;5;6\n", FileType.CSV)
    assert df.shape == (2, 3)
    assert list(df.columns) == ["a", "b", "c"]


def test_upload_malformed_xlsx_is_rejected(client: TestClient) -> None:
    _register_and_login(client, "badxlsx@example.com")
    project = _create_project(client)

    response = client.post(
        _upload_url(project["id"]),
        files={"file": ("bad.xlsx", b"this is not a real xlsx file at all")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unparseable_file"


def test_upload_empty_file_is_rejected(client: TestClient) -> None:
    _register_and_login(client, "empty@example.com")
    project = _create_project(client)

    response = client.post(_upload_url(project["id"]), files={"file": ("empty.csv", b"")})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "empty_file"


def test_upload_over_the_configured_size_limit_is_rejected(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "1")
    get_settings.cache_clear()

    _register_and_login(client, "toobig@example.com")
    project = _create_project(client)

    # Must genuinely exceed 1MB. Sized empirically, not by eye: the
    # original 50,000 two-column numeric rows came to only ~0.55MB, so
    # this test passed the limit check and asserted against a 201 that
    # was actually correct behavior. Wider+longer gets comfortably over.
    big_df = pd.DataFrame({col: range(60_000) for col in ("a", "b", "c", "d", "e")})
    payload = _csv_bytes(big_df)
    assert len(payload) > 1024 * 1024, (
        f"fixture is only {len(payload)} bytes - it must exceed the 1MB limit "
        "for this test to exercise anything"
    )
    response = client.post(_upload_url(project["id"]), files={"file": ("big.csv", payload)})

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_upload_with_a_path_traversal_filename_is_sanitized_not_rejected(
    client: TestClient,
) -> None:
    _register_and_login(client, "traversal@example.com")
    project = _create_project(client)

    response = client.post(
        _upload_url(project["id"]),
        files={"file": ("../../../etc/passwd.csv", _csv_bytes(_SAMPLE_DF))},
    )

    # The dangerous filename is neutralized, not treated as a hard
    # validation failure - the storage path was never derived from it
    # to begin with (server-generated key), so this is purely about
    # what gets displayed/stored as the on-record filename.
    assert response.status_code == 201, response.text
    stored_name = response.json()["file"]["original_filename"]
    assert ".." not in stored_name
    assert "/" not in stored_name


# --- auth / ownership -----------------------------------------------------


def test_upload_requires_authentication(client: TestClient) -> None:
    _register_and_login(client, "authcheck@example.com")
    project = _create_project(client)
    client.post("/api/v1/auth/logout")

    response = client.post(_upload_url(project["id"]), files={"file": ("d.csv", b"a,b\n1,2\n")})
    assert response.status_code == 401


def test_upload_requires_project_ownership(client: TestClient) -> None:
    _register_and_login(client, "owner-up@example.com")
    project = _create_project(client)

    _register_and_login(client, "intruder-up@example.com")  # switches the client's session
    response = client.post(
        _upload_url(project["id"]), files={"file": ("d.csv", _csv_bytes(_SAMPLE_DF))}
    )
    assert response.status_code == 404


# --- V1 one-file-per-project rule ------------------------------------------


def test_second_upload_to_the_same_project_is_rejected(client: TestClient) -> None:
    _register_and_login(client, "second@example.com")
    project = _create_project(client)

    first = client.post(
        _upload_url(project["id"]), files={"file": ("first.csv", _csv_bytes(_SAMPLE_DF))}
    )
    assert first.status_code == 201

    second = client.post(
        _upload_url(project["id"]), files={"file": ("second.csv", _csv_bytes(_SAMPLE_DF))}
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "file_already_exists"


def test_get_profile_returns_the_stored_profiling_result(client: TestClient) -> None:
    _register_and_login(client, "profileget@example.com")
    project = _create_project(client)
    client.post(_upload_url(project["id"]), files={"file": ("d.csv", _csv_bytes(_SAMPLE_DF))})

    response = client.get(f"{PROJECTS_URL}/{project['id']}/profile")
    assert response.status_code == 200
    assert response.json()["row_count"] == 3


def test_get_profile_before_any_upload_is_404(client: TestClient) -> None:
    _register_and_login(client, "noprofile@example.com")
    project = _create_project(client)

    response = client.get(f"{PROJECTS_URL}/{project['id']}/profile")
    assert response.status_code == 404


# --- GET /projects/{id}/file --------------------------------------------


def test_get_file_info_returns_the_uploaded_files_metadata(client: TestClient) -> None:
    _register_and_login(client, "fileinfo@example.com")
    project = _create_project(client)
    upload = client.post(
        _upload_url(project["id"]), files={"file": ("sales.csv", _csv_bytes(_SAMPLE_DF))}
    )

    response = client.get(f"{PROJECTS_URL}/{project['id']}/file")
    assert response.status_code == 200
    body = response.json()
    assert body == upload.json()["file"]
    assert body["original_filename"] == "sales.csv"
    assert body["file_type"] == "csv"


def test_get_file_info_before_any_upload_is_404(client: TestClient) -> None:
    _register_and_login(client, "nofileinfo@example.com")
    project = _create_project(client)

    response = client.get(f"{PROJECTS_URL}/{project['id']}/file")
    assert response.status_code == 404


def test_get_file_info_requires_authentication_and_ownership(client: TestClient) -> None:
    _register_and_login(client, "owner-fi@example.com")
    project = _create_project(client)
    client.post(_upload_url(project["id"]), files={"file": ("d.csv", _csv_bytes(_SAMPLE_DF))})
    url = f"{PROJECTS_URL}/{project['id']}/file"

    _register_and_login(client, "intruder-fi@example.com")  # switches the client's session
    foreign = client.get(url)
    missing = client.get(f"{PROJECTS_URL}/00000000-0000-0000-0000-000000000000/file")
    assert foreign.status_code == 404
    assert foreign.json() == missing.json()  # ownership is not probeable

    client.post("/api/v1/auth/logout")
    assert client.get(url).status_code == 401
