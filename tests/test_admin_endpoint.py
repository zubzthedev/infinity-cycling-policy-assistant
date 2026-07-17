"""Integration tests for the /api/admin/* endpoints."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import policies, prompts
from app.auth import AuthenticatedUser, get_current_user
from app.config import Settings, get_settings
from app.main import app as fastapi_app

ADMIN_USER = AuthenticatedUser(uid="a1", email="admin@example.com", is_admin=True)
NON_ADMIN_USER = AuthenticatedUser(uid="m1", email="member@example.com", is_admin=False)


def make_settings(policy_dir: Path, prompt_dir: Path, **overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "authorised_users": {"member@example.com", "admin@example.com"},
        "admin_users": {"admin@example.com"},
        "policy_dir": policy_dir,
        "prompt_dir": prompt_dir,
    }
    defaults.update(overrides)
    return Settings(**defaults)


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    """A temp policy/prompt directory pair, seeded with minimal real content
    and loaded into the module-level caches, so admin actions never touch
    the repo's actual policies/prompts."""
    policy_dir = tmp_path / "policies"
    policy_dir.mkdir()
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "system.md").write_text("SYSTEM", encoding="utf-8")
    (prompt_dir / "response_rules.md").write_text("RULES", encoding="utf-8")
    (prompt_dir / "examples.md").write_text("EXAMPLES", encoding="utf-8")
    (policy_dir / "constitution.md").write_text(
        "# Constitution\n\n## 6.2 Voting\n\nBody.\n", encoding="utf-8"
    )
    policies.reload_store(policy_dir)
    prompts.reload_prompts(prompt_dir)
    return policy_dir, prompt_dir


@pytest.fixture
def admin_client(dirs: tuple[Path, Path]) -> Generator[TestClient, None, None]:
    policy_dir, prompt_dir = dirs
    fastapi_app.dependency_overrides[get_settings] = lambda: make_settings(policy_dir, prompt_dir)
    fastapi_app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    yield TestClient(fastapi_app)
    fastapi_app.dependency_overrides.clear()


def test_status_requires_authentication(dirs: tuple[Path, Path]) -> None:
    policy_dir, prompt_dir = dirs
    fastapi_app.dependency_overrides[get_settings] = lambda: make_settings(policy_dir, prompt_dir)
    unauth_client = TestClient(fastapi_app)

    response = unauth_client.get("/api/admin/status")

    assert response.status_code == 401
    fastapi_app.dependency_overrides.clear()


def test_status_rejects_non_admin(dirs: tuple[Path, Path]) -> None:
    policy_dir, prompt_dir = dirs
    fastapi_app.dependency_overrides[get_settings] = lambda: make_settings(policy_dir, prompt_dir)
    fastapi_app.dependency_overrides[get_current_user] = lambda: NON_ADMIN_USER
    non_admin_client = TestClient(fastapi_app)

    response = non_admin_client.get("/api/admin/status")

    assert response.status_code == 403
    fastapi_app.dependency_overrides.clear()


def test_status_returns_loaded_policies(admin_client: TestClient) -> None:
    response = admin_client.get("/api/admin/status")

    assert response.status_code == 200
    body = response.json()
    assert body["gemini_model"]
    assert body["policy_source"] == "local"
    assert body["prompts_loaded"] is True
    assert any(p["slug"] == "constitution" for p in body["policies"])
    assert body["policy_load_errors"] == []


def test_reload_picks_up_manually_added_local_file(
    admin_client: TestClient, dirs: tuple[Path, Path]
) -> None:
    policy_dir, _ = dirs
    (policy_dir / "membership.md").write_text("# Membership\n\nBody.\n", encoding="utf-8")

    response = admin_client.post("/api/admin/reload")

    assert response.status_code == 200
    body = response.json()
    assert any(p["slug"] == "membership" for p in body["policies"])


def test_reload_uses_drive_source_when_configured(
    dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    policy_dir, prompt_dir = dirs
    files = [{"id": "f1", "name": "racing.md", "modifiedTime": "2026-01-01T00:00:00.000Z"}]
    monkeypatch.setattr(policies, "_list_drive_markdown_files", lambda folder_id, creds: files)
    monkeypatch.setattr(
        policies, "_fetch_drive_file_content", lambda file_id, creds: "# Racing Policy\n"
    )

    fastapi_app.dependency_overrides[get_settings] = lambda: make_settings(
        policy_dir,
        prompt_dir,
        policy_source="drive",
        drive_folder_id="abc123",
        google_application_credentials="fake-creds.json",
    )
    fastapi_app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    client = TestClient(fastapi_app)

    response = client.post("/api/admin/reload")

    assert response.status_code == 200
    body = response.json()
    assert body["policy_source"] == "drive"
    assert any(p["slug"] == "racing" for p in body["policies"])
    fastapi_app.dependency_overrides.clear()
