"""
V1 upload/dataset hardening - unit tests.

These exercise `file_service` (parsing under limits) and the Content-Length
middleware directly, with no HTTP client and no database, so they pin the
*rules* precisely. The matching end-to-end behaviour through real HTTP
requests lives in test_upload_limits_api.py.
"""

from __future__ import annotations

import asyncio
import codecs
import io
import json
from collections.abc import MutableMapping
from typing import Any

import numpy as np
import pandas as pd
import pytest

from app.core.exceptions import PayloadTooLargeException, ValidationException
from app.core.upload_limit import MULTIPART_OVERHEAD_BYTES, UploadSizeLimitMiddleware
from app.models import FileType
from app.services import file_service
from app.services.file_service import UploadLimits

MB = 1024 * 1024


def _csv(rows: int, cols: int = 3) -> bytes:
    df = pd.DataFrame({f"c{j}": range(rows) for j in range(cols)})
    return df.to_csv(index=False).encode("utf-8")


def _xlsx(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False, sheet_name="Sheet1")
    return buf.getvalue()


def _xlsx_grid(rows: int, cols: int) -> bytes:
    return _xlsx(pd.DataFrame({f"c{j}": range(rows) for j in range(cols)}))


def _code(exc_info: pytest.ExceptionInfo[Any]) -> str:
    return str(exc_info.value.error_code)


# --- the configured limits --------------------------------------------------


def test_default_limits_are_the_v1_targets() -> None:
    limits = UploadLimits.defaults()
    assert limits.max_bytes_for(FileType.CSV) == 25 * MB
    assert limits.max_bytes_for(FileType.XLSX) == 10 * MB
    assert limits.max_rows == 100_000
    assert limits.max_columns == 100
    # The largest any type may send - what a pre-body Content-Length check uses.
    assert limits.hard_ceiling_bytes == 25 * MB


# --- rows: boundaries, enforced while parsing -------------------------------


def test_csv_with_exactly_the_maximum_rows_is_accepted() -> None:
    limits = UploadLimits(max_rows=50)
    df = file_service.parse_dataset(_csv(50), FileType.CSV, limits)
    assert df.shape == (50, 3)


def test_csv_with_one_row_over_the_maximum_is_rejected() -> None:
    limits = UploadLimits(max_rows=50)
    with pytest.raises(ValidationException) as exc_info:
        file_service.parse_dataset(_csv(51), FileType.CSV, limits)
    assert _code(exc_info) == "too_many_rows"
    assert exc_info.value.details == {"limit": 50}
    assert "50" in exc_info.value.message


def test_csv_row_limit_stops_the_parser_instead_of_reading_the_whole_file() -> None:
    """A malformed row placed AFTER the limit is never reached: the file is
    refused as 'too many rows', not as 'unparseable'. With no limits (the
    legacy path) the same bytes fail to parse - which proves the limited
    parse really stopped early rather than loading everything first."""
    body = b"a,b\n" + b"1,2\n" * 30 + b"1,2,3,4,5\n"

    with pytest.raises(ValidationException) as limited:
        file_service.parse_dataset(body, FileType.CSV, UploadLimits(max_rows=10))
    assert _code(limited) == "too_many_rows"

    with pytest.raises(ValidationException) as legacy:
        file_service.parse_dataset(body, FileType.CSV)
    assert _code(legacy) == "unparseable_file"


def test_xlsx_with_exactly_the_maximum_rows_is_accepted() -> None:
    df = file_service.parse_dataset(_xlsx_grid(40, 3), FileType.XLSX, UploadLimits(max_rows=40))
    assert df.shape == (40, 3)


def test_xlsx_with_one_row_over_the_maximum_is_rejected() -> None:
    with pytest.raises(ValidationException) as exc_info:
        file_service.parse_dataset(_xlsx_grid(41, 3), FileType.XLSX, UploadLimits(max_rows=40))
    assert _code(exc_info) == "too_many_rows"


def test_xlsx_parse_is_told_to_stop_one_row_past_the_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The XLSX row limit is applied by the reader (`nrows`), not by loading
    the sheet and counting afterwards."""
    calls: list[dict[str, Any]] = []
    real_read_excel = pd.read_excel

    def spy(*args: Any, **kwargs: Any) -> pd.DataFrame:
        calls.append(kwargs)
        result = real_read_excel(*args, **kwargs)
        # read_excel is overloaded (DataFrame | dict of DataFrames); this call has no
        # `sheet_name=None`, so a DataFrame is what it must return.
        assert isinstance(result, pd.DataFrame)
        return result

    monkeypatch.setattr(pd, "read_excel", spy)
    file_service.parse_dataset(_xlsx_grid(5, 2), FileType.XLSX, UploadLimits(max_rows=40))

    assert [c.get("nrows") for c in calls] == [0, 41]  # header probe, then data


def test_legacy_parse_without_limits_still_reads_every_row() -> None:
    """Files accepted before limits existed must keep loading for analysis."""
    assert file_service.parse_dataset(_csv(150), FileType.CSV).shape[0] == 150
    with pytest.raises(ValidationException):
        file_service.parse_dataset(_csv(150), FileType.CSV, UploadLimits(max_rows=100))


# --- columns: boundaries, header inspected first ------------------------------


def test_csv_with_exactly_the_maximum_columns_is_accepted() -> None:
    df = file_service.parse_dataset(_csv(3, cols=5), FileType.CSV, UploadLimits(max_columns=5))
    assert df.shape == (3, 5)


def test_csv_with_one_column_over_the_maximum_is_rejected() -> None:
    with pytest.raises(ValidationException) as exc_info:
        file_service.parse_dataset(_csv(3, cols=6), FileType.CSV, UploadLimits(max_columns=5))
    assert _code(exc_info) == "too_many_columns"
    assert exc_info.value.details == {"limit": 5, "actual": 6}


def test_csv_width_is_judged_from_the_header_before_the_data_is_parsed() -> None:
    """The body is garbage (ragged rows). A too-wide header must still be
    reported as too many columns, proving the header is checked first."""
    header = ",".join(f"c{j}" for j in range(10))
    body = f"{header}\n1,2\n1,2,3,4,5,6,7,8,9,10,11,12\n".encode()
    with pytest.raises(ValidationException) as exc_info:
        file_service.parse_dataset(body, FileType.CSV, UploadLimits(max_columns=5))
    assert _code(exc_info) == "too_many_columns"


def test_xlsx_column_boundaries() -> None:
    limits = UploadLimits(max_columns=4)
    assert file_service.parse_dataset(_xlsx_grid(3, 4), FileType.XLSX, limits).shape == (3, 4)
    with pytest.raises(ValidationException) as exc_info:
        file_service.parse_dataset(_xlsx_grid(3, 5), FileType.XLSX, limits)
    assert _code(exc_info) == "too_many_columns"
    assert exc_info.value.details == {"limit": 4, "actual": 5}


def test_semicolon_delimited_csv_width_is_counted_with_the_detected_delimiter() -> None:
    body = b"a;b;c;d;e;f\n1;2;3;4;5;6\n"
    with pytest.raises(ValidationException) as exc_info:
        file_service.parse_dataset(body, FileType.CSV, UploadLimits(max_columns=3))
    assert exc_info.value.details == {"limit": 3, "actual": 6}


# --- empty and header-only ------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "content"),
    [
        ("header-only csv", b"a,b,c\n"),
        ("header-only csv, no trailing newline", b"a,b,c"),
        ("csv with blank data lines", b"a,b,c\n\n\n"),
    ],
)
def test_header_only_csv_is_rejected_as_no_data_rows(label: str, content: bytes) -> None:
    df = file_service.parse_dataset(content, FileType.CSV, UploadLimits())
    assert df.shape[0] == 0, label
    with pytest.raises(ValidationException) as exc_info:
        file_service.validate_dataset(df, UploadLimits())
    assert _code(exc_info) == "no_data_rows"


def test_header_only_xlsx_is_rejected_as_no_data_rows() -> None:
    content = _xlsx(pd.DataFrame(columns=["a", "b"]))
    df = file_service.parse_dataset(content, FileType.XLSX, UploadLimits())
    with pytest.raises(ValidationException) as exc_info:
        file_service.validate_dataset(df, UploadLimits())
    assert _code(exc_info) == "no_data_rows"


def test_a_file_whose_every_cell_is_empty_is_rejected() -> None:
    df = file_service.parse_dataset(b"a,b\n,\n,\n", FileType.CSV, UploadLimits())
    with pytest.raises(ValidationException) as exc_info:
        file_service.validate_dataset(df, UploadLimits())
    assert _code(exc_info) == "no_data_rows"


def test_a_normal_dataset_passes_validation() -> None:
    df = file_service.parse_dataset(_csv(5), FileType.CSV, UploadLimits())
    file_service.validate_dataset(df, UploadLimits())  # does not raise


def test_whitespace_only_csv_is_an_empty_file_not_a_malformed_one() -> None:
    with pytest.raises(ValidationException) as exc_info:
        file_service.parse_dataset(b"   \n\n", FileType.CSV, UploadLimits())
    assert _code(exc_info) == "empty_file"


def test_xlsx_with_an_empty_first_sheet_is_an_empty_file() -> None:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame().to_excel(writer, sheet_name="Empty", index=False)
        pd.DataFrame({"a": [1, 2]}).to_excel(writer, sheet_name="Data", index=False)
    with pytest.raises(ValidationException) as exc_info:
        file_service.parse_dataset(buf.getvalue(), FileType.XLSX, UploadLimits())
    assert _code(exc_info) == "empty_file"


# --- malformed files --------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "file_type", "content"),
    [
        ("ragged csv", FileType.CSV, b"a,b,c\n1,2,3,4,5,6\n"),
        ("binary named .csv", FileType.CSV, bytes(range(256)) * 20),
        ("not a zip at all", FileType.XLSX, b"this is not a real xlsx file"),
        ("csv text named .xlsx", FileType.XLSX, b"a,b\n1,2\n"),
        ("truncated xlsx", FileType.XLSX, _xlsx_grid(50, 2)[:300]),
        ("xlsx bytes named .csv", FileType.CSV, _xlsx_grid(5, 2)),
    ],
)
def test_malformed_files_are_rejected_as_unparseable(
    label: str, file_type: FileType, content: bytes
) -> None:
    with pytest.raises(ValidationException) as exc_info:
        file_service.parse_dataset(content, file_type, UploadLimits())
    assert _code(exc_info) in {"unparseable_file", "unsupported_encoding"}, label


def test_unsupported_file_types_are_rejected_with_the_supported_list() -> None:
    for name in ("data.xls", "data.txt", "data.json", "data.parquet", "datafile"):
        with pytest.raises(ValidationException) as exc_info:
            file_service.detect_file_type(name)
        assert _code(exc_info) == "unsupported_file_type"
        assert exc_info.value.details == {"supported_extensions": [".csv", ".xlsx"]}


def test_uppercase_extensions_are_accepted() -> None:
    assert file_service.detect_file_type("DATA.CSV") == FileType.CSV
    assert file_service.detect_file_type("Book.XLSX") == FileType.XLSX


# --- encodings ---------------------------------------------------------------------


def test_latin1_csv_is_refused_with_a_clear_encoding_error() -> None:
    content = "name,city\nJosé,Zürich\n".encode("latin-1")
    with pytest.raises(ValidationException) as exc_info:
        file_service.parse_dataset(content, FileType.CSV, UploadLimits())
    assert _code(exc_info) == "unsupported_encoding"
    assert "UTF-8" in exc_info.value.message
    assert exc_info.value.details == {"supported_encodings": ["utf-8", "utf-16"]}


def test_invalid_utf8_late_in_the_file_is_still_caught() -> None:
    content = b"a,b\n" + b"1,2\n" * 5000 + b"\xe9,2\n"
    with pytest.raises(ValidationException) as exc_info:
        file_service.parse_dataset(content, FileType.CSV, UploadLimits())
    assert _code(exc_info) == "unsupported_encoding"


def test_utf8_with_bom_is_accepted_and_the_bom_does_not_leak_into_a_column_name() -> None:
    content = codecs.BOM_UTF8 + b"name,age\nx,1\ny,2\n"
    df = file_service.parse_dataset(content, FileType.CSV, UploadLimits())
    assert list(df.columns) == ["name", "age"]


def test_utf16_with_bom_is_accepted() -> None:
    content = "name,age\nx,1\ny,2\n".encode("utf-16")  # Python writes a BOM
    df = file_service.parse_dataset(content, FileType.CSV, UploadLimits())
    assert list(df.columns) == ["name", "age"]
    assert df.shape == (2, 2)


def test_utf8_non_ascii_text_round_trips() -> None:
    content = "name,city\nJosé,Zürich\n".encode()
    df = file_service.parse_dataset(content, FileType.CSV, UploadLimits())
    assert df["city"].tolist() == ["Zürich"]


# --- xlsx archive guard ------------------------------------------------------------


def test_xlsx_that_unpacks_beyond_the_limit_is_refused_before_it_is_opened() -> None:
    content = _xlsx_grid(200, 5)
    with pytest.raises(PayloadTooLargeException) as exc_info:
        file_service.parse_dataset(
            content, FileType.XLSX, UploadLimits(max_xlsx_uncompressed_bytes=1000)
        )
    assert exc_info.value.error_code == "file_too_large"
    assert exc_info.value.status_code == 413
    assert (exc_info.value.details or {}).get("reason") == "uncompressed_size"


def test_a_normal_xlsx_is_not_affected_by_the_archive_guard() -> None:
    assert file_service.parse_dataset(_xlsx_grid(20, 3), FileType.XLSX, UploadLimits()).shape == (
        20,
        3,
    )


# --- per-type byte limits ----------------------------------------------------------


def test_file_too_large_error_names_the_type_and_limit() -> None:
    csv_error = file_service.file_too_large_error(FileType.CSV, 25 * MB)
    xlsx_error = file_service.file_too_large_error(FileType.XLSX, 10 * MB)
    assert csv_error.status_code == xlsx_error.status_code == 413
    assert csv_error.error_code == xlsx_error.error_code == "file_too_large"
    assert "CSV" in csv_error.message and "25 MB" in csv_error.message
    assert "Excel" in xlsx_error.message and "10 MB" in xlsx_error.message
    assert xlsx_error.details == {"limit_bytes": 10 * MB, "limit_mb": 10, "file_type": "xlsx"}


def test_ordinary_application_errors_carry_no_details_key() -> None:
    """API compatibility: errors that predate `details` keep exactly their old shape."""
    assert ValidationException("x", error_code="empty_file").details is None


# --- Content-Length middleware (raw ASGI, no framework) -----------------------------

UPLOAD_PATH = "/api/v1/projects/6f0c1d9e-0000-0000-0000-000000000000/upload"


async def _drive(
    *,
    limit: int,
    method: str = "POST",
    path: str = UPLOAD_PATH,
    headers: list[tuple[bytes, bytes]] | None = None,
    scope_type: str = "http",
) -> tuple[bool, list[MutableMapping[str, Any]]]:
    reached_app: list[bool] = []
    sent: list[MutableMapping[str, Any]] = []

    async def inner(
        scope: MutableMapping[str, Any], receive: Any, send: Any
    ) -> None:  # the real app
        reached_app.append(True)

    async def receive() -> MutableMapping[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(message)

    middleware = UploadSizeLimitMiddleware(
        inner, api_prefix="/api/v1", max_body_bytes=lambda: limit
    )
    scope: MutableMapping[str, Any] = {
        "type": scope_type,
        "method": method,
        "path": path,
        "headers": headers or [],
    }
    await middleware(scope, receive, send)
    return bool(reached_app), sent


def _cl(n: int | str) -> list[tuple[bytes, bytes]]:
    return [(b"content-length", str(n).encode())]


def test_middleware_rejects_an_oversized_declared_body_without_calling_the_app() -> None:
    reached, sent = asyncio.run(_drive(limit=25 * MB, headers=_cl(200 * MB)))
    assert reached is False
    assert sent[0]["status"] == 413
    assert (b"connection", b"close") in sent[0]["headers"]

    body = json.loads(sent[1]["body"])
    assert body["error"]["code"] == "file_too_large"
    assert body["error"]["details"]["limit_mb"] == 25


def test_middleware_lets_a_body_at_the_limit_through() -> None:
    limit = 25 * MB
    for declared in (1, limit, limit + MULTIPART_OVERHEAD_BYTES):
        reached, sent = asyncio.run(_drive(limit=limit, headers=_cl(declared)))
        assert reached is True and sent == [], declared


def test_middleware_rejects_just_past_limit_plus_overhead() -> None:
    limit = 25 * MB
    reached, sent = asyncio.run(
        _drive(limit=limit, headers=_cl(limit + MULTIPART_OVERHEAD_BYTES + 1))
    )
    assert reached is False and sent[0]["status"] == 413


def test_middleware_ignores_other_paths_methods_and_scope_types() -> None:
    huge = _cl(500 * MB)
    cases: list[dict[str, Any]] = [
        {"path": "/api/v1/projects"},  # create project
        {"path": "/api/v1/auth/login"},
        {"path": UPLOAD_PATH, "method": "GET"},
        {"path": UPLOAD_PATH + "/extra"},
        {"path": UPLOAD_PATH, "scope_type": "lifespan"},
    ]
    for case in cases:
        reached, sent = asyncio.run(_drive(limit=MB, headers=huge, **case))
        assert reached is True and sent == [], case


def test_middleware_defers_when_content_length_is_missing_or_malformed() -> None:
    for headers in ([], _cl("not-a-number"), _cl(-5)):
        reached, sent = asyncio.run(_drive(limit=MB, headers=headers))
        assert reached is True and sent == [], headers


def test_middleware_reads_the_limit_on_every_request() -> None:
    declared = _cl(3 * MB)
    allowed, _ = asyncio.run(_drive(limit=10 * MB, headers=declared))
    assert allowed is True
    rejected, sent = asyncio.run(_drive(limit=1, headers=_cl(3 * MB)))
    assert rejected is False and sent[0]["status"] == 413


def test_random_float_xlsx_size_is_predictable_enough_for_boundary_tests() -> None:
    """Guards the API tests' assumption that incompressible data makes an
    .xlsx comfortably larger than a few hundred KB (not a product behaviour)."""
    rng = np.random.default_rng(0)
    df = pd.DataFrame(rng.random((5_000, 10)))
    assert len(_xlsx(df)) > 300_000
