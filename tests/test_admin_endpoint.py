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
    assert body["prompts_loaded"] is True
    assert any(p["slug"] == "constitution" for p in body["policies"])
    assert body["policy_load_errors"] == []


def test_upload_creates_new_policy(admin_client: TestClient, dirs: tuple[Path, Path]) -> None:
    policy_dir, _ = dirs
    response = admin_client.post(
        "/api/admin/policies",
        files={"file": ("racing.md", b"# Racing Policy\n\nMarshal duties.\n", "text/markdown")},
    )

    assert response.status_code == 200
    body = response.json()
    assert any(p["slug"] == "racing" for p in body["policies"])
    assert (policy_dir / "racing.md").read_text(encoding="utf-8") == (
        "# Racing Policy\n\nMarshal duties.\n"
    )


def test_upload_replaces_existing_policy(admin_client: TestClient, dirs: tuple[Path, Path]) -> None:
    policy_dir, _ = dirs
    response = admin_client.post(
        "/api/admin/policies",
        files={"file": ("constitution.md", b"# Constitution\n\nUpdated body.\n", "text/markdown")},
    )

    assert response.status_code == 200
    assert (policy_dir / "constitution.md").read_text(encoding="utf-8") == (
        "# Constitution\n\nUpdated body.\n"
    )


def test_upload_rejects_non_markdown_extension(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/admin/policies",
        files={"file": ("notes.txt", b"not markdown", "text/plain")},
    )
    assert response.status_code == 400


def test_upload_rejects_oversized_file(admin_client: TestClient) -> None:
    oversized_content = b"x" * (500_000 + 1)
    response = admin_client.post(
        "/api/admin/policies",
        files={"file": ("big.md", oversized_content, "text/markdown")},
    )
    assert response.status_code == 413


def test_upload_sanitises_path_traversal_filename(
    admin_client: TestClient, dirs: tuple[Path, Path]
) -> None:
    policy_dir, _ = dirs
    response = admin_client.post(
        "/api/admin/policies",
        files={"file": ("../../evil.md", b"# Not Actually Evil\n", "text/markdown")},
    )

    assert response.status_code == 200
    assert (policy_dir / "evil.md").exists()
    assert not (policy_dir.parent.parent / "evil.md").exists()


def test_delete_removes_policy(admin_client: TestClient, dirs: tuple[Path, Path]) -> None:
    policy_dir, _ = dirs
    response = admin_client.delete("/api/admin/policies/constitution")

    assert response.status_code == 200
    body = response.json()
    assert all(p["slug"] != "constitution" for p in body["policies"])
    assert not (policy_dir / "constitution.md").exists()


def test_delete_unknown_slug_returns_404(admin_client: TestClient) -> None:
    response = admin_client.delete("/api/admin/policies/does-not-exist")
    assert response.status_code == 404


def test_reload_picks_up_manually_added_file(
    admin_client: TestClient, dirs: tuple[Path, Path]
) -> None:
    policy_dir, _ = dirs
    (policy_dir / "membership.md").write_text("# Membership\n\nBody.\n", encoding="utf-8")

    response = admin_client.post("/api/admin/reload")

    assert response.status_code == 200
    body = response.json()
    assert any(p["slug"] == "membership" for p in body["policies"])
