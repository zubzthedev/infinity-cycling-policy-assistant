"""Integration tests for POST /api/ask and the policy-reference parser."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import policies, prompts, rate_limit
from app.auth import AuthenticatedUser, get_current_user
from app.config import Settings, get_settings
from app.gemini import GeminiAPIError, GeminiTimeoutError
from app.main import app as fastapi_app
from app.routers import ask as ask_router

AUTHORISED_USER = AuthenticatedUser(uid="u1", email="member@example.com", is_admin=False)
REPO_ROOT = Path(__file__).resolve().parent.parent


def make_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "authorised_users": {"member@example.com"},
        "admin_users": set(),
        "rate_limit_per_minute": 1000,
    }
    defaults.update(overrides)
    return Settings(**defaults)


@pytest.fixture(autouse=True)
def _load_real_policies_and_prompts() -> None:
    # /api/ask reads from the module-level caches, not from settings.policy_dir,
    # so tests populate them directly from the real sample content.
    policies.reload_store(REPO_ROOT / "policies")
    prompts.reload_prompts(REPO_ROOT / "prompts")


@pytest.fixture(autouse=True)
def _reset_rate_limit_state() -> None:
    rate_limit._requests.clear()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    fastapi_app.dependency_overrides[get_settings] = lambda: make_settings()
    fastapi_app.dependency_overrides[get_current_user] = lambda: AUTHORISED_USER
    yield TestClient(fastapi_app)
    fastapi_app.dependency_overrides.clear()


def test_ask_requires_authentication() -> None:
    fastapi_app.dependency_overrides[get_settings] = lambda: make_settings()
    unauth_client = TestClient(fastapi_app)

    response = unauth_client.post("/api/ask", json={"question": "Can a member be suspended?"})

    assert response.status_code == 401
    fastapi_app.dependency_overrides.clear()


def test_ask_returns_structured_response(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    canned_answer = (
        "## Applicable Policies\n\n* Constitution\n\n"
        "## Summary\n\nNo, not without declaring the conflict.\n\n"
        "## Reasoning\n\nSection 6.2 requires disclosure and withdrawal.\n\n"
        "## Recommended Process\n\nDeclare the conflict and withdraw from the vote.\n\n"
        "## Policy References\n\n* Constitution Section 6.2\n"
    )

    async def fake_ask_gemini(prompt: str, settings: Settings | None = None) -> str:
        return canned_answer

    monkeypatch.setattr(ask_router, "ask_gemini", fake_ask_gemini)

    response = client.post(
        "/api/ask",
        json={"question": "Can an EXCO member vote where they have a conflict of interest?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "<h2" in body["answer_html"]
    assert body["answer_markdown"] == canned_answer
    matched = next(
        (ref for ref in body["policy_references"] if ref["policy_slug"] == "constitution"), None
    )
    assert matched is not None
    assert matched["section_slug"] is not None


def test_ask_rejects_empty_question(client: TestClient) -> None:
    response = client.post("/api/ask", json={"question": ""})
    assert response.status_code == 422


def test_ask_rejects_overly_long_question(client: TestClient) -> None:
    response = client.post("/api/ask", json={"question": "x" * 2001})
    assert response.status_code == 422


def test_ask_maps_gemini_timeout_to_504(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_ask_gemini(prompt: str, settings: Settings | None = None) -> str:
        raise GeminiTimeoutError("timed out")

    monkeypatch.setattr(ask_router, "ask_gemini", fake_ask_gemini)

    response = client.post("/api/ask", json={"question": "Can a member be suspended?"})
    assert response.status_code == 504


def test_ask_maps_gemini_api_error_to_502(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_ask_gemini(prompt: str, settings: Settings | None = None) -> str:
        raise GeminiAPIError("failed")

    monkeypatch.setattr(ask_router, "ask_gemini", fake_ask_gemini)

    response = client.post("/api/ask", json={"question": "Can a member be suspended?"})
    assert response.status_code == 502


def test_ask_enforces_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    fastapi_app.dependency_overrides[get_settings] = lambda: make_settings(
        rate_limit_per_minute=2
    )
    fastapi_app.dependency_overrides[get_current_user] = lambda: AUTHORISED_USER

    async def fake_ask_gemini(prompt: str, settings: Settings | None = None) -> str:
        return "## Summary\n\nok\n"

    monkeypatch.setattr(ask_router, "ask_gemini", fake_ask_gemini)

    limited_client = TestClient(fastapi_app)
    for _ in range(2):
        response = limited_client.post("/api/ask", json={"question": "Can a member be suspended?"})
        assert response.status_code == 200

    response = limited_client.post("/api/ask", json={"question": "Can a member be suspended?"})
    assert response.status_code == 429

    fastapi_app.dependency_overrides.clear()


def test_extract_policy_references_matches_known_policy_and_section(tmp_path: Path) -> None:
    (tmp_path / "constitution.md").write_text(
        "# Constitution\n\n## 6.2 Voting and Conflicts of Interest\n\nBody.\n", encoding="utf-8"
    )
    store = policies.load_policies(tmp_path)

    answer = "## Policy References\n\n* Constitution Section 6.2\n"
    references = ask_router.extract_policy_references(answer, store)

    assert len(references) == 1
    assert references[0].policy_slug == "constitution"
    assert references[0].section_slug is not None


def test_extract_policy_references_returns_plain_text_when_no_match(tmp_path: Path) -> None:
    (tmp_path / "constitution.md").write_text("# Constitution\n", encoding="utf-8")
    store = policies.load_policies(tmp_path)

    answer = "## Policy References\n\n* Some Unknown Policy Section 9.9\n"
    references = ask_router.extract_policy_references(answer, store)

    assert len(references) == 1
    assert references[0].policy_slug is None
    assert references[0].section_slug is None


def test_extract_policy_references_returns_empty_when_no_references_heading() -> None:
    empty_store = policies.PolicyStore(policies={}, order=(), errors=())
    assert ask_router.extract_policy_references("no references here", empty_store) == []
