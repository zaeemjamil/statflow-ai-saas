"""Phase 9 Stage 2: the AI endpoints end to end (real HTTP app, SQLite test DB,
scripted fake provider). Covers auth/ownership, configuration, eligibility,
the evidence boundary, storage, staleness, limits and failure handling."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import prompt
from app.ai.provider import ProviderBusy, ProviderError, ProviderResult, ProviderTimeout
from app.api.deps import get_ai_provider
from app.core.config import get_settings
from app.models import Analysis, UsageRecord
from tests.ai_helpers import sample_frame

PROJECTS = "/api/v1/projects"
RENAMED = {
    "when": "order_date",
    "x": "ad_spend_eur",
    "y": "revenue_eur",
    "z": "discount_rate",
    "group": "region_code",
}
CITIES = {"north": "Kaiserslautern", "south": "Wuppertal", "east": "Zwickau", "west": "Hof"}

GOOD_REPLY: dict[str, Any] = {
    "summary": "Column_003 moves with Column_002 in this data.",
    "key_findings": ["Column_003 is associated with Column_002.", "Column_005 has 4 groups."],
    "data_quality": ["No major problems."],
    "limitations": ["Association only, not cause."],
    "next_steps": ["Look at Column_004."],
}


class FakeProvider:
    model = "fake/model"

    def __init__(self, reply: Any = None, error: Exception | None = None) -> None:
        self.reply = json.dumps(GOOD_REPLY) if reply is None else reply
        self.error = error
        self.calls: list[list[dict[str, str]]] = []

    def generate(self, messages: list[dict[str, str]]) -> ProviderResult:
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        text = self.reply if isinstance(self.reply, str) else json.dumps(self.reply)
        return ProviderResult(text=text, model="fake/model-1")


def _frame(rows: int = 40) -> pd.DataFrame:
    frame = sample_frame(rows).rename(columns=RENAMED)
    frame["region_code"] = frame["region_code"].map(CITIES)
    return frame


def _setup(client: TestClient, email: str, rows: int = 40, analyze: bool = True) -> str:
    assert (
        client.post(
            "/api/v1/auth/register", json={"email": email, "password": "correct-horse-1"}
        ).status_code
        == 201
    )
    pid = str(client.post(PROJECTS, json={"name": "AI"}).json()["id"])
    csv = _frame(rows).to_csv(index=False).encode()
    up = client.post(f"{PROJECTS}/{pid}/upload", files={"file": ("d.csv", csv, "text/csv")})
    assert up.status_code == 201, up.text
    if analyze:
        assert client.post(f"{PROJECTS}/{pid}/analyze").status_code == 200
    return pid


def _install(client: TestClient, provider: FakeProvider | None) -> None:
    client.app.dependency_overrides[get_ai_provider] = lambda: provider  # type: ignore[attr-defined]


@pytest.fixture()
def no_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_COOLDOWN_SECONDS", "0")
    get_settings.cache_clear()


# --- access ---------------------------------------------------------------


def test_endpoints_require_login(client: TestClient) -> None:
    pid = "00000000-0000-0000-0000-000000000001"
    assert client.get(f"{PROJECTS}/{pid}/ai-insights").status_code == 401
    assert client.post(f"{PROJECTS}/{pid}/ai-insights").status_code == 401


def test_another_users_project_is_a_404_for_both_verbs(client: TestClient) -> None:
    _install(client, FakeProvider())
    pid = _setup(client, "owner@example.com")
    client.post("/api/v1/auth/logout")
    client.post(
        "/api/v1/auth/register",
        json={"email": "intruder@example.com", "password": "correct-horse-1"},
    )
    assert client.get(f"{PROJECTS}/{pid}/ai-insights").status_code == 404
    assert client.post(f"{PROJECTS}/{pid}/ai-insights").status_code == 404


def test_a_project_without_an_analysis_is_a_404(client: TestClient) -> None:
    _install(client, FakeProvider())
    pid = _setup(client, "noanalysis@example.com", analyze=False)
    assert client.get(f"{PROJECTS}/{pid}/ai-insights").status_code == 404


# --- configuration and eligibility ---------------------------------------


def test_without_a_key_the_feature_is_off_and_nothing_is_sent(client: TestClient) -> None:
    _install(client, None)
    pid = _setup(client, "nokey@example.com")
    state = client.get(f"{PROJECTS}/{pid}/ai-insights").json()
    assert state["configured"] is False and state["eligible"] is True and state["insight"] is None
    refused = client.post(f"{PROJECTS}/{pid}/ai-insights")
    assert refused.status_code == 503
    assert refused.json()["error"]["code"] == "ai_not_configured"


def test_too_few_rows_is_refused_with_the_reason_and_no_provider_call(client: TestClient) -> None:
    fake = FakeProvider()
    _install(client, fake)
    pid = _setup(client, "tiny@example.com", rows=4)
    state = client.get(f"{PROJECTS}/{pid}/ai-insights").json()
    assert state["eligible"] is False and state["reason_code"] == "too_few_rows"
    response = client.post(f"{PROJECTS}/{pid}/ai-insights")
    assert response.status_code == 409 and response.json()["error"]["code"] == "too_few_rows"
    assert fake.calls == []


def test_small_samples_are_allowed_and_flagged_independently_of_the_model(
    client: TestClient, no_cooldown: None
) -> None:
    _install(client, FakeProvider())
    pid = _setup(client, "small@example.com", rows=12)
    state = client.get(f"{PROJECTS}/{pid}/ai-insights").json()
    assert state["eligible"] is True and "small_sample" in state["warnings"]
    done = client.post(f"{PROJECTS}/{pid}/ai-insights").json()
    assert "small_sample" in done["insight"]["evidence_warnings"]


# --- the happy path and the evidence boundary ----------------------------


def test_generation_stores_aliased_text_and_shows_real_names(
    client: TestClient, db_session: Session, no_cooldown: None
) -> None:
    fake = FakeProvider()
    _install(client, fake)
    pid = _setup(client, "happy@example.com")

    posted = client.post(f"{PROJECTS}/{pid}/ai-insights")
    assert posted.status_code == 200, posted.text
    insight = posted.json()["insight"]
    assert "revenue_eur" in insight["summary"] and "ad_spend_eur" in insight["summary"]
    assert "Column_00" not in json.dumps(insight)
    assert insight["model"] == "fake/model-1" and insight["prompt_version"] == prompt.PROMPT_VERSION
    assert client.get(f"{PROJECTS}/{pid}/ai-insights").json()["insight"] == insight

    stored = db_session.execute(select(Analysis)).scalar_one().ai_insights
    assert stored is not None
    assert "Column_003" in stored["insight"]["summary"]  # aliased at rest
    for real in (*RENAMED.values(), *CITIES.values()):
        assert real not in json.dumps(stored)

    (messages,) = fake.calls
    sent = json.dumps(messages)
    for real in (*RENAMED.values(), *CITIES.values()):
        assert real not in sent  # nothing identifying left the server
    assert messages[1]["content"].count(prompt.EVIDENCE_START) == 1


def test_a_stored_explanation_is_withheld_once_the_analysis_changes(
    client: TestClient, no_cooldown: None
) -> None:
    _install(client, FakeProvider())
    pid = _setup(client, "stale@example.com")
    assert client.post(f"{PROJECTS}/{pid}/ai-insights").status_code == 200
    assert (
        client.post(
            f"{PROJECTS}/{pid}/regression",
            json={"target": "revenue_eur", "predictors": ["ad_spend_eur"]},
        ).status_code
        == 200
    )
    state = client.get(f"{PROJECTS}/{pid}/ai-insights").json()
    assert state["insight"] is None and state["has_outdated_insight"] is True
    assert client.post(f"{PROJECTS}/{pid}/ai-insights").json()["insight"] is not None


def test_recleaning_drops_the_old_explanation(
    client: TestClient, db_session: Session, no_cooldown: None
) -> None:
    _install(client, FakeProvider())
    pid = _setup(client, "reclean@example.com")
    client.post(f"{PROJECTS}/{pid}/ai-insights")
    client.post(f"{PROJECTS}/{pid}/clean", json={"duplicate_strategy": "remove"})
    assert db_session.execute(select(Analysis)).scalar_one().ai_insights is None


# --- untrusted output ----------------------------------------------------


def test_hostile_model_output_is_neutralised(client: TestClient, no_cooldown: None) -> None:
    hostile = {
        "summary": "Visit https://evil.example now. Column_999 is great.\u202e",
        "key_findings": ["<script>alert(1)</script> Column_003"],
        "limitations": [],
    }
    _install(client, FakeProvider(reply=hostile))
    pid = _setup(client, "hostile@example.com")
    body = client.post(f"{PROJECTS}/{pid}/ai-insights").json()["insight"]
    assert "evil.example" not in body["summary"] and "\u202e" not in body["summary"]
    assert "[unknown column]" in body["summary"] and "Column_999" not in body["summary"]
    assert "revenue_eur" in body["key_findings"][0]  # still only plain text for the UI


@pytest.mark.parametrize("reply", ["not json at all", "[]", {"no_summary": True}, ""])
def test_unusable_output_is_a_502_and_stores_nothing(
    client: TestClient, db_session: Session, no_cooldown: None, reply: Any
) -> None:
    _install(client, FakeProvider(reply=reply))
    pid = _setup(client, "badout@example.com")
    response = client.post(f"{PROJECTS}/{pid}/ai-insights")
    assert response.status_code == 502 and response.json()["error"]["code"] == "ai_invalid_response"
    assert db_session.execute(select(Analysis)).scalar_one().ai_insights is None


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ProviderError(), "ai_provider_error"),
        (ProviderTimeout(), "ai_provider_timeout"),
        (ProviderBusy(), "ai_provider_busy"),
    ],
)
def test_provider_failures_are_502s_with_safe_messages(
    client: TestClient, no_cooldown: None, error: ProviderError, code: str
) -> None:
    _install(client, FakeProvider(error=error))
    pid = _setup(client, f"fail-{code}@example.com")
    response = client.post(f"{PROJECTS}/{pid}/ai-insights")
    assert response.status_code == 502 and response.json()["error"]["code"] == code
    assert client.get(f"{PROJECTS}/{pid}/ai-insights").json()["insight"] is None


# --- limits ---------------------------------------------------------------


def test_cooldown_blocks_a_second_generation_straight_after_the_first(client: TestClient) -> None:
    fake = FakeProvider()
    _install(client, fake)
    pid = _setup(client, "cool@example.com")
    assert client.post(f"{PROJECTS}/{pid}/ai-insights").status_code == 200
    again = client.post(f"{PROJECTS}/{pid}/ai-insights")
    assert again.status_code == 429 and again.json()["error"]["code"] == "ai_rate_limited"
    assert again.json()["error"]["details"]["retry_after_seconds"] >= 1
    assert len(fake.calls) == 1


def test_daily_limit_counts_every_call_including_failures(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_COOLDOWN_SECONDS", "0")
    monkeypatch.setenv("AI_DAILY_LIMIT_PER_USER", "2")
    get_settings.cache_clear()
    fake = FakeProvider(error=ProviderError())
    _install(client, fake)
    pid = _setup(client, "limit@example.com")
    assert client.post(f"{PROJECTS}/{pid}/ai-insights").status_code == 502
    assert client.post(f"{PROJECTS}/{pid}/ai-insights").status_code == 502
    third = client.post(f"{PROJECTS}/{pid}/ai-insights")
    assert third.status_code == 429 and third.json()["error"]["code"] == "ai_daily_limit"
    assert len(fake.calls) == 2
    assert db_session.execute(select(UsageRecord)).scalar_one().count == 2
    assert client.get(f"{PROJECTS}/{pid}/ai-insights").json()["remaining_today"] == 0
