"""
V1 upload/dataset hardening - end-to-end tests through real HTTP requests.

Limits are lowered per test via environment variables (the same mechanism
the existing size-limit test in test_upload.py uses) so boundaries can be
exercised with small, fast fixtures. The exact rules are pinned by the
unit tests in test_upload_limits_unit.py.
"""

from __future__ import annotations

import io
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.exceptions import PayloadTooLargeException
from app.core.upload_limit import UploadSizeLimitMiddleware
from app.main import create_app
from app.models import FileType
from app.services.file_service import UploadLimits

PROJECTS_URL = "/api/v1/projects"
MB = 1024 * 1024


def _register_and_login(client: TestClient, email: str, password: str = "correct-horse-1") -> None:
    response = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201, response.text


def _create_project(client: TestClient, name: str = "Limits") -> dict[str, Any]:
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


def _grid(rows: int, cols: int) -> pd.DataFrame:
    return pd.DataFrame({f"c{j}": range(rows) for j in range(cols)})


def _set_limit(monkeypatch: pytest.MonkeyPatch, name: str, value: int) -> None:
    monkeypatch.setenv(name, str(value))
    get_settings.cache_clear()


def _project_status(client: TestClient, project_id: str) -> str:
    response = client.get(f"{PROJECTS_URL}/{project_id}")
    assert response.status_code == 200, response.text
    return str(response.json()["status"])


# --- empty / header-only: rejected BEFORE the project leaves `created` ---------


@pytest.mark.parametrize("kind", ["csv", "xlsx"])
def test_header_only_upload_is_rejected_and_the_project_is_not_marked_profiled(
    client: TestClient, kind: str
) -> None:
    _register_and_login(client, f"headeronly-{kind}@example.com")
    project = _create_project(client)
    header_only = pd.DataFrame(columns=["a", "b", "c"])
    payload = _csv_bytes(header_only) if kind == "csv" else _xlsx_bytes(header_only)

    response = client.post(_upload_url(project["id"]), files={"file": (f"empty.{kind}", payload)})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "no_data_rows"
    assert _project_status(client, project["id"]) == "created"
    assert client.get(f"{PROJECTS_URL}/{project['id']}/file").status_code == 404

    # ...and the project is still usable: a real file can be uploaded after.
    retry = client.post(
        _upload_url(project["id"]), files={"file": ("ok.csv", _csv_bytes(_grid(5, 2)))}
    )
    assert retry.status_code == 201, retry.text
    assert _project_status(client, project["id"]) == "profiled"


def test_zero_byte_upload_is_rejected_without_a_details_key(client: TestClient) -> None:
    """Errors that predate structured `details` keep exactly their old shape."""
    _register_and_login(client, "zerobyte@example.com")
    project = _create_project(client)

    response = client.post(_upload_url(project["id"]), files={"file": ("e.csv", b"")})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "empty_file"
    assert "details" not in response.json()["error"]


# --- rows / columns -----------------------------------------------------------------


def test_row_limit_boundary_through_the_api(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_limit(monkeypatch, "MAX_DATASET_ROWS", 20)
    _register_and_login(client, "rows@example.com")

    at_limit = _create_project(client, "at limit")
    ok = client.post(
        _upload_url(at_limit["id"]), files={"file": ("a.csv", _csv_bytes(_grid(20, 3)))}
    )
    assert ok.status_code == 201, ok.text

    over = _create_project(client, "over limit")
    rejected = client.post(
        _upload_url(over["id"]), files={"file": ("b.csv", _csv_bytes(_grid(21, 3)))}
    )
    assert rejected.status_code == 422
    error = rejected.json()["error"]
    assert error["code"] == "too_many_rows"
    assert error["details"] == {"limit": 20}
    assert _project_status(client, over["id"]) == "created"


def test_column_limit_boundary_through_the_api(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_limit(monkeypatch, "MAX_DATASET_COLUMNS", 3)
    _register_and_login(client, "cols@example.com")

    at_limit = _create_project(client, "at limit")
    ok = client.post(
        _upload_url(at_limit["id"]), files={"file": ("a.csv", _csv_bytes(_grid(5, 3)))}
    )
    assert ok.status_code == 201, ok.text

    over = _create_project(client, "over limit")
    for name, payload in (
        ("b.csv", _csv_bytes(_grid(5, 4))),
        ("b.xlsx", _xlsx_bytes(_grid(5, 4))),
    ):
        rejected = client.post(_upload_url(over["id"]), files={"file": (name, payload)})
        assert rejected.status_code == 422, name
        error = rejected.json()["error"]
        assert error["code"] == "too_many_columns", name
        assert error["details"] == {"limit": 3, "actual": 4}, name
    assert _project_status(client, over["id"]) == "created"


# --- per-type byte limits ------------------------------------------------------------


def test_csv_size_limit_is_enforced_with_a_structured_413(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_limit(monkeypatch, "MAX_CSV_UPLOAD_SIZE_MB", 1)
    _register_and_login(client, "csvsize@example.com")
    project = _create_project(client)

    payload = _csv_bytes(pd.DataFrame({col: range(60_000) for col in "abcde"}))
    assert len(payload) > MB, "fixture must exceed the 1 MB limit to exercise anything"

    response = client.post(_upload_url(project["id"]), files={"file": ("big.csv", payload)})

    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == "file_too_large"
    assert "CSV" in error["message"]
    assert error["details"] == {"limit_bytes": MB, "limit_mb": 1, "file_type": "csv"}


def test_xlsx_limit_is_separate_from_and_lower_than_the_csv_limit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the XLSX limit at 1 MB and CSV left at its 25 MB default, a
    >1 MB .xlsx is refused while a >1 MB .csv is accepted."""
    _set_limit(monkeypatch, "MAX_XLSX_UPLOAD_SIZE_MB", 1)
    _register_and_login(client, "xlsxsize@example.com")

    rng = np.random.default_rng(0)  # random floats do not compress: size is predictable
    xlsx_payload = _xlsx_bytes(pd.DataFrame(rng.random((25_000, 10))))
    assert len(xlsx_payload) > MB, "fixture must exceed the 1 MB XLSX limit"
    xlsx_project = _create_project(client, "xlsx")
    refused = client.post(
        _upload_url(xlsx_project["id"]), files={"file": ("big.xlsx", xlsx_payload)}
    )
    assert refused.status_code == 413
    error = refused.json()["error"]
    assert error["code"] == "file_too_large"
    assert "Excel" in error["message"]
    assert error["details"]["file_type"] == "xlsx"

    csv_payload = _csv_bytes(pd.DataFrame({col: range(60_000) for col in "abcde"}))
    assert len(csv_payload) > MB
    csv_project = _create_project(client, "csv")
    accepted = client.post(_upload_url(csv_project["id"]), files={"file": ("big.csv", csv_payload)})
    assert accepted.status_code == 201, accepted.text


# --- encodings, types, ordering --------------------------------------------------------


def test_non_utf8_csv_gets_a_clear_encoding_error(client: TestClient) -> None:
    _register_and_login(client, "latin1@example.com")
    project = _create_project(client)
    payload = "name,city\nJosé,Zürich\n".encode("latin-1")

    response = client.post(_upload_url(project["id"]), files={"file": ("l1.csv", payload)})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "unsupported_encoding"
    assert "UTF-8" in error["message"]
    assert error["details"] == {"supported_encodings": ["utf-8", "utf-16"]}


def test_utf8_bom_csv_uploads_and_the_column_name_is_clean(client: TestClient) -> None:
    _register_and_login(client, "bom@example.com")
    project = _create_project(client)
    payload = b"\xef\xbb\xbfname,age\nx,1\ny,2\n"

    response = client.post(_upload_url(project["id"]), files={"file": ("bom.csv", payload)})

    assert response.status_code == 201, response.text
    names = [c["name"] for c in response.json()["profile"]["columns"]]
    assert names == ["name", "age"]


def test_unsupported_extension_reports_what_is_supported(client: TestClient) -> None:
    _register_and_login(client, "ext2@example.com")
    project = _create_project(client)

    response = client.post(_upload_url(project["id"]), files={"file": ("d.xls", b"whatever")})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "unsupported_file_type"
    assert error["details"] == {"supported_extensions": [".csv", ".xlsx"]}


def test_a_second_upload_conflicts_before_its_type_or_body_is_examined(
    client: TestClient,
) -> None:
    _register_and_login(client, "order@example.com")
    project = _create_project(client)
    first = client.post(
        _upload_url(project["id"]), files={"file": ("one.csv", _csv_bytes(_grid(5, 2)))}
    )
    assert first.status_code == 201

    second = client.post(_upload_url(project["id"]), files={"file": ("two.txt", b"nope")})

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "file_already_exists"


# --- the bounded reader, the limits object, settings, middleware wiring ------------------


def test_read_bounded_accepts_exactly_the_limit_and_rejects_one_byte_more() -> None:
    from app.api.v1.uploads import _read_bounded

    exact = UploadFile(file=io.BytesIO(b"x" * 1000), filename="a.csv")
    assert len(_read_bounded(exact, 1000, FileType.CSV)) == 1000

    over = UploadFile(file=io.BytesIO(b"x" * 1001), filename="a.csv")
    with pytest.raises(PayloadTooLargeException) as exc_info:
        _read_bounded(over, 1000, FileType.CSV)
    assert exc_info.value.error_code == "file_too_large"


def test_upload_limits_from_settings_apply_the_overall_ceiling() -> None:
    capped = UploadLimits.from_settings(
        Settings.model_construct(
            MAX_UPLOAD_SIZE_MB=1,
            MAX_CSV_UPLOAD_SIZE_MB=25,
            MAX_XLSX_UPLOAD_SIZE_MB=10,
            MAX_DATASET_ROWS=100_000,
            MAX_DATASET_COLUMNS=100,
            MAX_XLSX_UNCOMPRESSED_SIZE_MB=250,
        )
    )
    assert capped.max_csv_bytes == MB and capped.max_xlsx_bytes == MB

    roomy = UploadLimits.from_settings(
        Settings.model_construct(
            MAX_UPLOAD_SIZE_MB=100,
            MAX_CSV_UPLOAD_SIZE_MB=25,
            MAX_XLSX_UPLOAD_SIZE_MB=10,
            MAX_DATASET_ROWS=100_000,
            MAX_DATASET_COLUMNS=100,
            MAX_XLSX_UNCOMPRESSED_SIZE_MB=250,
        )
    )
    assert roomy.max_csv_bytes == 25 * MB and roomy.max_xlsx_bytes == 10 * MB


def test_settings_defaults_are_the_v1_limits() -> None:
    settings = Settings(DATABASE_URL="postgresql://u:p@localhost:5432/db", _env_file=None)
    assert settings.MAX_CSV_UPLOAD_SIZE_MB == 25
    assert settings.MAX_XLSX_UPLOAD_SIZE_MB == 10
    assert settings.MAX_DATASET_ROWS == 100_000
    assert settings.MAX_DATASET_COLUMNS == 100


@pytest.mark.parametrize(
    "name",
    [
        "MAX_UPLOAD_SIZE_MB",
        "MAX_CSV_UPLOAD_SIZE_MB",
        "MAX_XLSX_UPLOAD_SIZE_MB",
        "MAX_DATASET_ROWS",
        "MAX_DATASET_COLUMNS",
    ],
)
def test_a_zero_or_negative_limit_is_refused_at_startup(name: str) -> None:
    for bad in (0, -1):
        # model_validate runs the field validators without reading the
        # environment or a .env file, so only the value under test matters.
        with pytest.raises(ValidationError):
            Settings.model_validate(
                {"DATABASE_URL": "postgresql://u:p@localhost:5432/db", name: bad}
            )


def test_the_content_length_middleware_is_installed_inside_cors() -> None:
    app = create_app()
    # Typed as plain objects: Starlette types `.cls` as a middleware *factory*, which
    # mypy (rightly) will not compare against the concrete classes asserted on below.
    classes: list[object] = [m.cls for m in app.user_middleware]
    assert UploadSizeLimitMiddleware in classes
    # First in the list = outermost. CORS must wrap the limiter so an early
    # 413 still carries CORS headers.
    assert classes.index(CORSMiddleware) < classes.index(UploadSizeLimitMiddleware)
