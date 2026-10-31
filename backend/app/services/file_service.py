"""
File upload orchestration: validate -> parse -> profile -> store ->
persist. Sync throughout, matching the rest of the codebase (Phase 3's
sync-SQLAlchemy decision) - pandas parsing is sync anyway, so there's no
benefit to an async path here.
"""

from __future__ import annotations

import codecs
import csv
import io
import re
import uuid
import warnings
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import data_quality
from app.analytics.data_quality import ImportNote
from app.analytics.profiling import profile_dataset
from app.core.exceptions import (
    ConflictException,
    PayloadTooLargeException,
    ValidationException,
)
from app.models import File, FileType, Project, ProjectStatus
from app.services.storage_service import StorageService

if TYPE_CHECKING:  # annotation only: keeps this module importable without pydantic-settings
    from app.core.config import Settings

_MB = 1024 * 1024
_FILENAME_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._ -]")
_MAX_FILENAME_LENGTH = 255
_CSV_SAMPLE_BYTES = 8192
# The header row is inspected before the data is parsed, to reject a
# too-wide file without tokenising it. A header longer than this is not a
# plausible <=100-column header, so it is treated as malformed.
_CSV_MAX_HEADER_BYTES = 1024 * 1024
SUPPORTED_ENCODINGS = ("utf-8", "utf-16")
# Stage 3: the text "NA" is NOT treated as missing by the parser (it is
# resolved per column in data_quality.resolve_na_text, and reported). Every
# other pandas default missing token keeps its old meaning.
_NA_READ_KWARGS: dict[str, Any] = {
    "keep_default_na": False,
    "na_values": list(data_quality.NA_TOKENS_WITHOUT_NA),
}
# Projects uploaded before Stage 3 were parsed with pandas' stock missing-value
# tokens (which include "NA"); their stored profile counts reflect that. A
# re-read of such a file keeps that policy so the data analysed matches the
# profile shown to the user (see is_legacy_upload).
_LEGACY_NA_READ_KWARGS: dict[str, Any] = {}
_MAX_WORKBOOK_XML_BYTES = 1024 * 1024


def sanitize_filename(filename: str) -> str:
    """For display/storage in files.original_filename only - never used
    as an actual filesystem path (storage keys are server-generated,
    see storage_service.py). Strips any directory components (defends
    against a client sending "../../etc/passwd" as a "filename") and
    replaces anything outside a conservative safe-character set."""
    name = Path(filename).name  # strips any directory components
    name = _FILENAME_UNSAFE_CHARS.sub("_", name).strip()
    return (name or "upload")[:_MAX_FILENAME_LENGTH]


def detect_file_type(filename: str) -> FileType:
    """Extension only - the client's declared MIME type is never
    trusted (requirement). The authoritative content check is that
    parse_dataset() can actually read the bytes as that type."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        return FileType.CSV
    if suffix == ".xlsx":
        return FileType.XLSX
    raise ValidationException(
        "Only .csv and .xlsx files are supported.",
        error_code="unsupported_file_type",
        details={"supported_extensions": [".csv", ".xlsx"]},
    )


_TYPE_LABEL = {FileType.CSV: "CSV", FileType.XLSX: "Excel (.xlsx)"}


@dataclass(frozen=True)
class UploadLimits:
    """Everything an upload is checked against. Built from Settings by the
    endpoint; `defaults()` mirrors the Settings defaults so direct callers
    (tests, scripts) get the V1 limits without a Settings object.

    `max_bytes_*` already has the MAX_UPLOAD_SIZE_MB ceiling folded in, so
    nothing downstream has to remember to apply it.
    """

    max_csv_bytes: int = 25 * _MB
    max_xlsx_bytes: int = 10 * _MB
    max_rows: int = 100_000
    max_columns: int = 100
    max_xlsx_uncompressed_bytes: int = 250 * _MB

    @classmethod
    def defaults(cls) -> UploadLimits:
        return cls()

    @classmethod
    def from_settings(cls, settings: Settings) -> UploadLimits:
        ceiling = settings.MAX_UPLOAD_SIZE_MB * _MB
        return cls(
            max_csv_bytes=min(settings.MAX_CSV_UPLOAD_SIZE_MB * _MB, ceiling),
            max_xlsx_bytes=min(settings.MAX_XLSX_UPLOAD_SIZE_MB * _MB, ceiling),
            max_rows=settings.MAX_DATASET_ROWS,
            max_columns=settings.MAX_DATASET_COLUMNS,
            max_xlsx_uncompressed_bytes=settings.MAX_XLSX_UNCOMPRESSED_SIZE_MB * _MB,
        )

    def max_bytes_for(self, file_type: FileType) -> int:
        return self.max_csv_bytes if file_type == FileType.CSV else self.max_xlsx_bytes

    @property
    def hard_ceiling_bytes(self) -> int:
        """The largest body any supported type may send. The only size known
        before the filename (hence the type) is, e.g. for a Content-Length
        pre-check."""
        return max(self.max_csv_bytes, self.max_xlsx_bytes)


def file_too_large_error(file_type: FileType, max_bytes: int) -> PayloadTooLargeException:
    label = _TYPE_LABEL[file_type]
    limit_mb = max_bytes // _MB
    return PayloadTooLargeException(
        f"This {label} file is larger than the {limit_mb} MB limit for {label} files.",
        error_code="file_too_large",
        details={
            "limit_bytes": max_bytes,
            "limit_mb": limit_mb,
            "file_type": file_type.value,
        },
    )


def _too_many_rows(limit: int) -> ValidationException:
    return ValidationException(
        f"This file has more than {limit:,} data rows, which is the maximum Zaimex "
        "supports. Remove rows or upload a smaller extract of the data.",
        error_code="too_many_rows",
        details={"limit": limit},
    )


def _too_many_columns(limit: int, actual: int) -> ValidationException:
    return ValidationException(
        f"This file has {actual:,} columns, but the maximum is {limit:,}. "
        "Remove unneeded columns and upload again.",
        error_code="too_many_columns",
        details={"limit": limit, "actual": actual},
    )


def _unsupported_encoding() -> ValidationException:
    return ValidationException(
        "This CSV file is not UTF-8 text, so its characters can't be read reliably. "
        "Re-save it as UTF-8 (in Excel: Save As > 'CSV UTF-8 (Comma delimited)') "
        "and upload it again.",
        error_code="unsupported_encoding",
        details={"supported_encodings": list(SUPPORTED_ENCODINGS)},
    )


def ensure_project_has_no_file(db: Session, project: Project) -> None:
    # V1 constraint: one project = one file. A second upload is a
    # conflict to reject, not something to silently replace.
    existing = db.scalar(select(File).where(File.project_id == project.id))
    if existing is not None:
        raise ConflictException(
            "This project already has an uploaded file. Zaimex V1 supports one file per project.",
            error_code="file_already_exists",
        )


def _detect_csv_encoding(content: bytes) -> str:
    """UTF-8 (with or without BOM) or BOM-marked UTF-16/32. Anything else is
    refused with a clear message rather than guessed at: decoding cp1252 or
    Latin-2 bytes as something else produces plausible-looking wrong text,
    and a column name or category that is quietly corrupted is worse than an
    upload that is refused with instructions."""
    if content.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        return "utf-32"  # checked before UTF-16: the UTF-32-LE BOM begins with the UTF-16-LE BOM
    if content.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    if content.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if b"\x00" in content[:_CSV_SAMPLE_BYTES]:
        # NUL bytes in what should be text without a UTF-16/32 BOM: this is a
        # binary file with a .csv name, not an encoding problem.
        raise ValidationException(
            "Could not parse this file as a valid CSV file. "
            "It looks like a binary file rather than text.",
            error_code="unparseable_file",
        )
    return "utf-8"


def _is_decode_error(exc: BaseException) -> bool:
    return isinstance(exc, UnicodeError) or isinstance(exc.__cause__, UnicodeError)


def _check_csv_width(content: bytes, encoding: str, delimiter: str, limits: UploadLimits) -> None:
    """Reject a too-wide CSV from its header row alone, before any data row is
    tokenised. (Quoted header cells containing a newline would truncate the
    line, which can only under-count; the post-parse check backstops that.)"""
    head = content[:_CSV_MAX_HEADER_BYTES].decode(encoding, errors="ignore").lstrip("\ufeff")
    first_line, newline, _ = head.partition("\n")
    if not newline and len(content) > _CSV_MAX_HEADER_BYTES:
        raise ValidationException(
            "Could not parse this file as a valid CSV file. Its header row is unreasonably long.",
            error_code="unparseable_file",
        )
    try:
        field_count = len(next(csv.reader([first_line.rstrip("\r")], delimiter=delimiter), []))
    except csv.Error:
        return  # let the real parser produce the error
    if field_count > limits.max_columns:
        raise _too_many_columns(limits.max_columns, field_count)


def _detect_csv_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","  # single-column or otherwise ambiguous - comma is a safe default


def is_legacy_upload(profile: dict[str, Any] | None) -> bool:
    """True for a file uploaded before Stage 3. Every Stage 3+ upload profile
    carries an `import_notes` list (possibly empty); earlier profiles (and files
    with no stored profile at all) do not. No migration or new column needed.
    """
    return profile is None or "import_notes" not in profile


def parse_dataset(
    content: bytes,
    file_type: FileType,
    limits: UploadLimits | None = None,
    *,
    legacy_na_policy: bool = False,
) -> pd.DataFrame:
    """The parsed table only. See `parse_dataset_with_notes` for the full
    description; analysis re-reads of a stored file use this and therefore get
    exactly the same table the upload profiled."""
    df, _ = parse_dataset_with_notes(content, file_type, limits, legacy_na_policy=legacy_na_policy)
    return df


def parse_dataset_with_notes(
    content: bytes,
    file_type: FileType,
    limits: UploadLimits | None = None,
    *,
    legacy_na_policy: bool = False,
) -> tuple[pd.DataFrame, list[ImportNote]]:
    """The real content/parseability check: a file with the right
    extension but garbage content fails here, not silently later.

    CSV parsing needs three settings together to actually reject a
    ragged file, each covering a hole the others leave - verified
    empirically against `a,b,c\\n1,2,3,4,5,6\\n`:

    * Explicit delimiter (detected via csv.Sniffer) rather than pandas'
      `sep=None` sniffing mode, which silently mis-parses inconsistent
      row lengths instead of raising.
    * `index_col=False`. Without it, pandas quietly absorbs the 3 extra
      fields by promoting the first three values into a row *index*,
      yielding a plausible-looking (1, 3) DataFrame containing wrong
      values - no error, no warning. This is the subtlest of the three.
    * `ParserWarning` promoted to an error. `index_col=False` alone
      stops the corruption but then silently *truncates* the extra
      fields, emitting only a warning - still data loss the user is
      never told about.

    `on_bad_lines="error"` covers the ordinary ragged-row case but not
    the header-shorter-than-data case above, which is why all of this is
    needed rather than just that one flag.

    XLSX reads only the first worksheet - Phase 6 scope, documented
    here and in the Phase 6 report.

    V1 hardening - limits are applied *during* parsing, not after:

    * `limits=None` (default) is the legacy, unbounded behaviour. It exists
      for re-reading a file that was already accepted at upload (a project
      uploaded before limits existed must keep working) - never for a new
      upload, which always passes explicit limits.
    * With limits, CSV/XLSX are read with `nrows=max_rows + 1`, so the parser
      stops one row past the limit instead of materialising an arbitrarily
      long file; getting max_rows + 1 back means "too many rows". The column
      count is taken from the header row first (CSV: a csv.reader over the
      first line; XLSX: a `nrows=0` read) so a too-wide file is refused
      before its data is parsed. An .xlsx whose declared uncompressed size is
      over the limit is refused before openpyxl opens it.
    * CSV text is decoded by the parser from the raw bytes (no whole-file
      `str` + StringIO copies) and only UTF-8/UTF-16 are accepted.

    Stage 3: the second return value is the list of import notes found while
    reading (the text "NA", blank/duplicate headers, ignored worksheets) -
    see app/analytics/data_quality.py. The table itself is never altered by
    them except that "NA" is resolved per column (and reported).

    `legacy_na_policy=True` is for re-reading a file uploaded before Stage 3
    (see `is_legacy_upload`): pandas' stock missing-value tokens are used,
    "NA" included, exactly as when that file was profiled, and no notes are
    produced. A new upload never uses it.
    """
    na_kwargs = _LEGACY_NA_READ_KWARGS if legacy_na_policy else _NA_READ_KWARGS
    try:
        if file_type == FileType.CSV:
            df = _parse_csv(content, limits, na_kwargs)
        else:
            df = _parse_xlsx(content, limits, na_kwargs)
    except (ValidationException, PayloadTooLargeException):
        raise  # already a specific, user-facing error
    except Exception as exc:
        if file_type == FileType.CSV and _is_decode_error(exc):
            raise _unsupported_encoding() from exc
        if isinstance(exc, pd.errors.EmptyDataError):
            raise ValidationException(
                "This file is empty: it contains no header row and no data.",
                error_code="empty_file",
            ) from exc
        raise ValidationException(
            f"Could not parse this file as a valid {file_type.value.upper()} file. "
            "Check that it's a well-formed, uncorrupted file.",
            error_code="unparseable_file",
        ) from exc

    if df.shape[1] == 0:
        raise ValidationException("This file has no columns.", error_code="empty_file")
    # The parser was told to stop at max_rows + 1, so getting more than
    # max_rows back means the file really has more rows than allowed.
    if limits is not None and df.shape[0] > limits.max_rows:
        raise _too_many_rows(limits.max_rows)

    if legacy_na_policy:
        return df, []
    df, notes = _apply_import_checks(df, content, file_type)
    return df, notes


def _apply_import_checks(
    df: pd.DataFrame, content: bytes, file_type: FileType
) -> tuple[pd.DataFrame, list[ImportNote]]:
    notes: list[ImportNote] = []
    if file_type == FileType.XLSX:
        sheet_note = data_quality.extra_sheets_note(_xlsx_sheet_names(content))
        if sheet_note is not None:
            notes.append(sheet_note)
    notes.extend(data_quality.detect_header_issues([str(c) for c in df.columns]))
    df, na_notes = data_quality.resolve_na_text(df)
    notes.extend(na_notes)
    return df, notes


def _xlsx_sheet_names(content: bytes) -> list[str]:
    """Worksheet names in workbook order, read straight from xl/workbook.xml
    (a few KB; avoids a third full workbook load). Best effort: a note is a
    courtesy, so anything unexpected yields [] rather than failing an upload
    that parsed fine."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            with archive.open("xl/workbook.xml") as handle:
                raw = handle.read(_MAX_WORKBOOK_XML_BYTES + 1)
        if len(raw) > _MAX_WORKBOOK_XML_BYTES:
            return []
        root = ET.fromstring(raw)
        return [
            element.attrib["name"]
            for element in root.iter()
            if element.tag.rsplit("}", 1)[-1] == "sheet" and "name" in element.attrib
        ]
    except Exception:
        return []


def _parse_csv(
    content: bytes, limits: UploadLimits | None, na_kwargs: dict[str, Any]
) -> pd.DataFrame:
    encoding = _detect_csv_encoding(content)
    sample = content[:_CSV_SAMPLE_BYTES].decode(encoding, errors="ignore").lstrip("\ufeff")
    delimiter = _detect_csv_delimiter(sample)
    if limits is not None:
        _check_csv_width(content, encoding, delimiter, limits)
    with warnings.catch_warnings():
        warnings.simplefilter("error", pd.errors.ParserWarning)
        df: pd.DataFrame = pd.read_csv(
            io.BytesIO(content),
            sep=delimiter,
            encoding=encoding,
            on_bad_lines="error",
            index_col=False,
            nrows=None if limits is None else limits.max_rows + 1,
            **na_kwargs,
        )
    return df


def _parse_xlsx(
    content: bytes, limits: UploadLimits | None, na_kwargs: dict[str, Any]
) -> pd.DataFrame:
    if limits is None:
        return pd.read_excel(io.BytesIO(content), sheet_name=0, **na_kwargs)

    # Not a valid zip -> BadZipFile -> "unparseable_file" via the caller.
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        uncompressed = sum(member.file_size for member in archive.infolist())
    if uncompressed > limits.max_xlsx_uncompressed_bytes:
        limit_mb = limits.max_xlsx_uncompressed_bytes // _MB
        raise PayloadTooLargeException(
            f"This Excel file contains more than {limit_mb} MB of data once unpacked, "
            "which is over the limit. Remove unused sheets or rows, or export it as CSV.",
            error_code="file_too_large",
            details={
                "reason": "uncompressed_size",
                "limit_bytes": limits.max_xlsx_uncompressed_bytes,
                "file_type": "xlsx",
            },
        )

    # Header only (nrows=0 reads just the first row): refuse a too-wide sheet
    # before parsing any of its data.
    header = pd.read_excel(io.BytesIO(content), sheet_name=0, nrows=0, **na_kwargs)
    if header.shape[1] > limits.max_columns:
        raise _too_many_columns(limits.max_columns, header.shape[1])
    return pd.read_excel(io.BytesIO(content), sheet_name=0, nrows=limits.max_rows + 1, **na_kwargs)


def validate_dataset(df: pd.DataFrame, limits: UploadLimits) -> None:
    """Checks that need the parsed frame. Runs for every new upload, before
    anything is stored or the project leaves its current status.

    The row/column checks repeat what parsing already enforced on purpose:
    they cost nothing and keep the guarantee true even if a parser path ever
    stops applying its own limit."""
    if df.shape[0] > limits.max_rows:
        raise _too_many_rows(limits.max_rows)
    if df.shape[1] > limits.max_columns:
        raise _too_many_columns(limits.max_columns, df.shape[1])
    if df.shape[0] == 0:
        raise ValidationException(
            "This file has column headers but no data rows. Add at least one row of data "
            "and upload it again.",
            error_code="no_data_rows",
        )
    if bool(df.isna().all().all()):
        raise ValidationException(
            "Every data cell in this file is empty, so there is nothing to analyse.",
            error_code="no_data_rows",
        )


def generate_storage_key(project_id: uuid.UUID, file_type: FileType) -> str:
    """Server-generated and opaque - the client never chooses a storage
    path (explicit requirement). Nothing client-supplied appears in
    this string at all, which is what actually rules out path
    traversal here, not the storage layer's own defense-in-depth check
    alone."""
    return f"uploads/{project_id}/{uuid.uuid4().hex}.{file_type.value}"


def process_upload(
    db: Session,
    *,
    project: Project,
    filename: str,
    content: bytes,
    storage: StorageService,
    limits: UploadLimits | None = None,
) -> tuple[File, dict[str, Any]]:
    limits = limits or UploadLimits.defaults()
    ensure_project_has_no_file(db, project)

    if not content:
        raise ValidationException("The uploaded file is empty.", error_code="empty_file")

    file_type = detect_file_type(filename)
    # The endpoint already stops reading at this limit; checking again here
    # keeps the rule true for any other caller of the service.
    if len(content) > limits.max_bytes_for(file_type):
        raise file_too_large_error(file_type, limits.max_bytes_for(file_type))

    df, import_notes = parse_dataset_with_notes(content, file_type, limits)
    validate_dataset(df, limits)
    # Stage 3: the upload profile also carries the data-correctness findings
    # (identifiers, formatted numbers, ambiguous dates, import notes).
    profile = profile_dataset(df, inspect_data_quality=True, import_notes=import_notes)

    storage_key = generate_storage_key(project.id, file_type)
    storage.save_file(storage_key=storage_key, content=content)

    file_row = File(
        project_id=project.id,
        storage_key=storage_key,
        original_filename=sanitize_filename(filename),
        file_type=file_type,
        size_bytes=len(content),
        row_count=profile["row_count"],
        column_count=profile["column_count"],
        profile=profile,
    )
    db.add(file_row)
    # Both transitions are real even though they happen within one
    # request: profiling is computed synchronously as part of upload,
    # so there's no meaningful "uploaded but not yet profiled" moment
    # to preserve - the project goes straight to PROFILED. Every check above
    # runs first, so a rejected file never changes the project's status.
    project.status = ProjectStatus.PROFILED

    db.commit()
    db.refresh(file_row)
    return file_row, profile
