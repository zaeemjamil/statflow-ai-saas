"""Phase 9 Stage 1 against real stored analyses: upload -> analyse through the
HTTP API, then build evidence from the saved database row. No AI endpoint
exists yet; this proves the evidence layer works on what is really persisted
and matches what the API shows."""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import eligibility
from app.ai.eligibility import EvidenceNotEligible
from app.ai.evidence import build_evidence_packet
from app.ai.loader import evidence_build_for_analysis, evidence_packet_for_analysis
from app.models import Analysis
from app.schemas.analysis import AnalysisPublic
from tests.ai_helpers import sample_frame

PROJECTS = "/api/v1/projects"


def _project_with_upload(client: TestClient, email: str, csv: bytes | None = None) -> str:
    registered = client.post(
        "/api/v1/auth/register", json={"email": email, "password": "correct-horse-1"}
    )
    assert registered.status_code == 201, registered.text
    created = client.post(PROJECTS, json={"name": "Evidence"})
    assert created.status_code == 201, created.text
    pid = str(created.json()["id"])
    csv = csv if csv is not None else sample_frame().to_csv(index=False).encode()
    uploaded = client.post(
        f"{PROJECTS}/{pid}/upload", files={"file": ("data.csv", csv, "text/csv")}
    )
    assert uploaded.status_code == 201, uploaded.text
    return pid


def _row(db: Session, project_id: str) -> Analysis:
    db.expire_all()
    return db.scalars(select(Analysis).where(Analysis.project_id == uuid.UUID(project_id))).one()


def test_evidence_from_a_stored_analysis_matches_what_the_api_returns(
    client: TestClient, db_session: Session
) -> None:
    pid = _project_with_upload(client, "ev1@example.com")
    assert client.post(f"{PROJECTS}/{pid}/analyze").status_code == 200
    regression = client.post(
        f"{PROJECTS}/{pid}/regression", json={"target": "y", "predictors": ["x", "z"]}
    )
    assert regression.status_code == 200, regression.text

    row_build = evidence_build_for_analysis(_row(db_session, pid))
    from_row = row_build.packet
    from_api = build_evidence_packet(
        AnalysisPublic.model_validate(client.get(f"{PROJECTS}/{pid}/analysis").json())
    )
    assert from_row.fingerprint == from_api.fingerprint
    assert from_row.content["coverage"]["regression"] == "included"
    assert from_row.content["regression"]["target"] == row_build.aliases.alias_for("y")
    assert "y" not in {c["column"] for c in from_row.content["columns"]}


def test_loading_twice_is_stable_and_leaks_no_stored_identifiers(
    client: TestClient, db_session: Session
) -> None:
    pid = _project_with_upload(client, "ev2@example.com")
    client.post(f"{PROJECTS}/{pid}/analyze")
    row = _row(db_session, pid)
    one, two = evidence_packet_for_analysis(row), evidence_packet_for_analysis(row)
    assert one.fingerprint == two.fingerprint
    serialized = json.dumps(one.content)
    for identifier in (row.id, row.project_id, row.file_id):
        assert str(identifier) not in serialized
    assert "data.csv" not in serialized  # file name is not evidence


def test_a_project_that_was_only_cleaned_is_not_eligible_yet(
    client: TestClient, db_session: Session
) -> None:
    pid = _project_with_upload(client, "ev3@example.com")
    assert client.post(f"{PROJECTS}/{pid}/clean", json={}).status_code == 200
    with pytest.raises(EvidenceNotEligible) as caught:
        evidence_packet_for_analysis(_row(db_session, pid))
    assert caught.value.error_code == eligibility.ANALYSIS_NOT_COMPLETED


def test_recleaning_with_a_different_choice_changes_the_fingerprint(
    client: TestClient, db_session: Session
) -> None:
    pid = _project_with_upload(client, "ev4@example.com")
    client.post(f"{PROJECTS}/{pid}/analyze")
    before = evidence_packet_for_analysis(_row(db_session, pid)).fingerprint

    assert (
        client.post(f"{PROJECTS}/{pid}/clean", json={"duplicate_strategy": "remove"}).status_code
        == 200
    )
    client.post(f"{PROJECTS}/{pid}/analyze")
    after = evidence_packet_for_analysis(_row(db_session, pid)).fingerprint
    # The numbers may be identical (no duplicates in this file) but the
    # recorded cleaning choice is part of the evidence.
    assert after != before


def test_evidence_survives_a_failed_regression_attempt_unchanged(
    client: TestClient, db_session: Session
) -> None:
    pid = _project_with_upload(client, "ev5@example.com")
    client.post(f"{PROJECTS}/{pid}/analyze")
    before = evidence_packet_for_analysis(_row(db_session, pid)).fingerprint
    bad = client.post(
        f"{PROJECTS}/{pid}/regression", json={"target": "no_such_column", "predictors": ["x"]}
    )
    assert bad.status_code == 422
    assert evidence_packet_for_analysis(_row(db_session, pid)).fingerprint == before


def test_a_small_upload_is_eligible_with_a_small_sample_warning(
    client: TestClient, db_session: Session
) -> None:
    csv = sample_frame(rows=12).to_csv(index=False).encode()
    pid = _project_with_upload(client, "ev6@example.com", csv)
    assert client.post(f"{PROJECTS}/{pid}/analyze").status_code == 200
    packet = evidence_packet_for_analysis(_row(db_session, pid))
    assert packet.content["warnings"] == [
        {"code": "small_sample", "rows_after_cleaning": 12, "threshold_rows": 30}
    ]
    # The 40-row upload used by the other tests carries no warning.
    pid_big = _project_with_upload(client, "ev7@example.com")
    client.post(f"{PROJECTS}/{pid_big}/analyze")
    assert evidence_packet_for_analysis(_row(db_session, pid_big)).content["warnings"] == []


def test_a_too_small_upload_is_refused_with_too_few_rows(
    client: TestClient, db_session: Session
) -> None:
    csv = sample_frame(rows=4).to_csv(index=False).encode()
    pid = _project_with_upload(client, "ev8@example.com", csv)
    assert client.post(f"{PROJECTS}/{pid}/analyze").status_code == 200
    with pytest.raises(EvidenceNotEligible) as caught:
        evidence_packet_for_analysis(_row(db_session, pid))
    assert caught.value.error_code == eligibility.TOO_FEW_ROWS


def test_a_stored_upload_with_distinctive_names_and_values_leaks_neither(
    client: TestClient, db_session: Session
) -> None:
    frame = sample_frame()
    frame = frame.rename(
        columns={"x": "ZZ_REVENUE_SENTINEL", "y": "ZZ_COST_SENTINEL", "group": "ZZ_REGION_SENTINEL"}
    )
    frame["ZZ_REGION_SENTINEL"] = "ZZ_CELL_" + frame["ZZ_REGION_SENTINEL"]
    pid = _project_with_upload(client, "ev9@example.com", frame.to_csv(index=False).encode())
    client.post(f"{PROJECTS}/{pid}/analyze")
    build = evidence_build_for_analysis(_row(db_session, pid))
    packet = build.packet
    text = json.dumps(packet.content, ensure_ascii=False)
    assert "ZZ_" not in text and "SENTINEL" not in text
    assert build.aliases.original_for("Column_002") == "ZZ_REVENUE_SENTINEL"
