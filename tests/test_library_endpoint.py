"""Integration tests for GET /api/policies (the Policy Library data API)."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import policies, prompts
from app.auth import AuthenticatedUser, get_current_user
from app.config import Settings, get_settings
from app.main import app as fastapi_app

AUTHORISED_USER = AuthenticatedUser(uid="u1", email="member@example.com", is_admin=False)
REPO_ROOT = Path(__file__).resolve().parent.parent


def make_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "authorised_users": {"member@example.com"},
        "admin_users": set(),
    }
    defaults.update(overrides)
    return Settings(**defaults)


@pytest.fixture(autouse=True)
def _load_real_policies_and_prompts() -> None:
    policies.reload_store(REPO_ROOT / "policies")
    prompts.reload_prompts(REPO_ROOT / "prompts")


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    fastapi_app.dependency_overrides[get_settings] = lambda: make_settings()
    fastapi_app.dependency_overrides[get_current_user] = lambda: AUTHORISED_USER
    yield TestClient(fastapi_app)
    fastapi_app.dependency_overrides.clear()


def test_list_policies_requires_authentication() -> None:
    fastapi_app.dependency_overrides[get_settings] = lambda: make_settings()
    unauth_client = TestClient(fastapi_app)

    response = unauth_client.get("/api/policies")

    assert response.status_code == 401
    fastapi_app.dependency_overrides.clear()


def test_list_policies_returns_every_loaded_document(client: TestClient) -> None:
    response = client.get("/api/policies")

    assert response.status_code == 200
    body = response.json()
    slugs = {doc["slug"] for doc in body["documents"]}
    assert slugs == {"constitution", "disciplinary", "membership", "racing", "code-of-conduct"}


def test_list_policies_includes_rendered_html_and_prefixed_section_slugs(
    client: TestClient,
) -> None:
    response = client.get("/api/policies")

    body = response.json()
    constitution = next(doc for doc in body["documents"] if doc["slug"] == "constitution")

    assert "<h2" in constitution["html"] or "<h1" in constitution["html"]
    section_slugs = [section["slug"] for section in constitution["sections"]]
    assert all(slug.startswith("constitution--") for slug in section_slugs)
    assert any("6.2" in section["heading"] for section in constitution["sections"])


def test_library_page_renders_without_authentication() -> None:
    """The /library shell itself carries no policy content, so it's public -
    real access control lives in GET /api/policies."""
    unauth_client = TestClient(fastapi_app)

    response = unauth_client.get("/library")

    assert response.status_code == 200
    assert "library-content" in response.text
