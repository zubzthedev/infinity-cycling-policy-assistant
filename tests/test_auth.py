"""Tests for Firebase token verification and the email allow-list layer."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from firebase_admin import auth as firebase_auth

from app import auth
from app.config import Settings, get_settings
from app.main import app as fastapi_app


def make_settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        "authorised_users": {"member@example.com", "admin@example.com"},
        "admin_users": {"admin@example.com"},
    }
    defaults.update(overrides)
    return Settings(**defaults)


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    fastapi_app.dependency_overrides[get_settings] = lambda: make_settings()
    yield TestClient(fastapi_app)
    fastapi_app.dependency_overrides.clear()


def test_whoami_requires_authorization_header(client: TestClient) -> None:
    response = client.get("/api/whoami")
    assert response.status_code == 401


def test_whoami_rejects_malformed_header(client: TestClient) -> None:
    response = client.get("/api/whoami", headers={"Authorization": "Basic abc"})
    assert response.status_code == 401


def test_whoami_rejects_invalid_token(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_verify(token: str) -> dict[str, Any]:
        raise firebase_auth.InvalidIdTokenError("bad token")

    monkeypatch.setattr(auth, "_verify_id_token", fake_verify)
    response = client.get("/api/whoami", headers={"Authorization": "Bearer bad-token"})
    assert response.status_code == 401


def test_whoami_rejects_unauthorised_email(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auth,
        "_verify_id_token",
        lambda token: {"uid": "u1", "email": "stranger@example.com"},
    )
    response = client.get("/api/whoami", headers={"Authorization": "Bearer token"})
    assert response.status_code == 403


def test_whoami_accepts_authorised_email_case_insensitively(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auth,
        "_verify_id_token",
        lambda token: {"uid": "u1", "email": "Member@Example.com"},
    )
    response = client.get("/api/whoami", headers={"Authorization": "Bearer token"})
    assert response.status_code == 200
    assert response.json() == {"email": "member@example.com", "is_admin": False}


def test_admin_ping_rejects_non_admin(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auth, "_verify_id_token", lambda token: {"uid": "u1", "email": "member@example.com"}
    )
    response = client.get("/api/admin/ping", headers={"Authorization": "Bearer token"})
    assert response.status_code == 403


def test_admin_ping_allows_admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auth, "_verify_id_token", lambda token: {"uid": "u2", "email": "admin@example.com"}
    )
    response = client.get("/api/admin/ping", headers={"Authorization": "Bearer token"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "admin": "admin@example.com"}
