"""Project CRUD + ownership tests, via real HTTP requests (see
conftest.py's `client` fixture)."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

PROJECTS_URL = "/api/v1/projects"


def _register_and_login(client: TestClient, email: str, password: str = "correct-horse-1") -> None:
    response = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201, response.text


def _create_project(client: TestClient, name: str = "Q3 Sales") -> dict[str, Any]:
    response = client.post(PROJECTS_URL, json={"name": name})
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


# --- CRUD, as the owner -------------------------------------------------


def test_create_project(client: TestClient) -> None:
    _register_and_login(client, "owner@example.com")
    response = client.post(PROJECTS_URL, json={"name": "Q3 Sales"})
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Q3 Sales"
    assert body["status"] == "created"
    assert "id" in body and "created_at" in body and "updated_at" in body


def test_list_own_projects(client: TestClient) -> None:
    _register_and_login(client, "owner@example.com")
    _create_project(client, "Project A")
    _create_project(client, "Project B")

    response = client.get(PROJECTS_URL)
    assert response.status_code == 200
    names = {p["name"] for p in response.json()}
    assert names == {"Project A", "Project B"}


def test_get_own_project(client: TestClient) -> None:
    _register_and_login(client, "owner@example.com")
    project = _create_project(client)

    response = client.get(f"{PROJECTS_URL}/{project['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == project["id"]


def test_get_nonexistent_project_is_404(client: TestClient) -> None:
    _register_and_login(client, "owner@example.com")
    response = client.get(f"{PROJECTS_URL}/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_update_own_project_renames_it(client: TestClient) -> None:
    _register_and_login(client, "owner@example.com")
    project = _create_project(client, "Old Name")

    response = client.patch(f"{PROJECTS_URL}/{project['id']}", json={"name": "New Name"})
    assert response.status_code == 200
    assert response.json()["name"] == "New Name"


def test_delete_own_project(client: TestClient) -> None:
    _register_and_login(client, "owner@example.com")
    project = _create_project(client)

    response = client.delete(f"{PROJECTS_URL}/{project['id']}")
    assert response.status_code == 204

    assert client.get(f"{PROJECTS_URL}/{project['id']}").status_code == 404


# --- unauthenticated access ----------------------------------------------


def test_list_projects_requires_authentication(client: TestClient) -> None:
    assert client.get(PROJECTS_URL).status_code == 401


def test_create_project_requires_authentication(client: TestClient) -> None:
    response = client.post(PROJECTS_URL, json={"name": "Nope"})
    assert response.status_code == 401


# --- cross-user isolation -------------------------------------------------


def test_user_a_cannot_get_user_b_project(client: TestClient) -> None:
    _register_and_login(client, "alice@example.com")
    project = _create_project(client, "Alice's Project")
    client.post("/api/v1/auth/logout")

    _register_and_login(client, "bob@example.com")
    response = client.get(f"{PROJECTS_URL}/{project['id']}")
    assert response.status_code == 404


def test_user_a_cannot_list_user_b_project(client: TestClient) -> None:
    _register_and_login(client, "alice@example.com")
    _create_project(client, "Alice's Project")
    client.post("/api/v1/auth/logout")

    _register_and_login(client, "bob@example.com")
    response = client.get(PROJECTS_URL)
    assert response.status_code == 200
    assert response.json() == []


def test_user_a_cannot_modify_user_b_project(client: TestClient) -> None:
    _register_and_login(client, "alice@example.com")
    project = _create_project(client, "Alice's Project")
    client.post("/api/v1/auth/logout")

    _register_and_login(client, "bob@example.com")
    response = client.patch(f"{PROJECTS_URL}/{project['id']}", json={"name": "Hijacked"})
    assert response.status_code == 404


def test_user_a_cannot_delete_user_b_project(client: TestClient) -> None:
    _register_and_login(client, "alice@example.com")
    project = _create_project(client, "Alice's Project")
    client.post("/api/v1/auth/logout")

    _register_and_login(client, "bob@example.com")
    response = client.delete(f"{PROJECTS_URL}/{project['id']}")
    assert response.status_code == 404

    # Confirm it's genuinely still there for the real owner, not just
    # that bob got a 404 while the delete silently went through anyway.
    client.post("/api/v1/auth/logout")
    response = client.post(
        "/api/v1/auth/login", json={"email": "alice@example.com", "password": "correct-horse-1"}
    )
    assert response.status_code == 200
    assert client.get(f"{PROJECTS_URL}/{project['id']}").status_code == 200
