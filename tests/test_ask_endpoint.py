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
from app.models.schemas import RESPONSE_SECTION_HEADINGS
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
    return Settings(_env_file=None, **defaults)


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
    matched = next(
        (ref for ref in body["policy_references"] if ref["policy_slug"] == "constitution"), None
    )
    assert matched is not None
    assert matched["section_slug"] is not None

    # The Policy References line is rewritten into a real Markdown link
    # pointing at the matched section's Policy Library anchor.
    expected_href = f"/library#{matched['section_slug']}"
    assert f"[Constitution Section 6.2]({expected_href})" in body["answer_markdown"]
    assert f'<a href="{expected_href}">Constitution Section 6.2</a>' in body["answer_html"]


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


def test_link_policy_references_rewrites_matched_line_as_markdown_link(tmp_path: Path) -> None:
    (tmp_path / "constitution.md").write_text(
        "# Constitution\n\n## 6.2 Voting and Conflicts of Interest\n\nBody.\n", encoding="utf-8"
    )
    store = policies.load_policies(tmp_path)
    answer = "## Policy References\n\n* Constitution Section 6.2\n"

    new_text, references = ask_router.link_policy_references(answer, store)

    assert len(references) == 1
    expected_href = f"/library#{references[0].section_slug}"
    assert f"* [Constitution Section 6.2]({expected_href})" in new_text


def test_link_policy_references_leaves_unmatched_line_as_plain_text(tmp_path: Path) -> None:
    (tmp_path / "constitution.md").write_text("# Constitution\n", encoding="utf-8")
    store = policies.load_policies(tmp_path)
    answer = "## Policy References\n\n* Some Unknown Policy Section 9.9\n"

    new_text, references = ask_router.link_policy_references(answer, store)

    assert new_text == answer
    assert references[0].policy_slug is None


def test_build_section_override_returns_empty_for_none() -> None:
    assert ask_router._build_section_override(None) == ""


def test_build_section_override_returns_empty_when_all_sections_selected() -> None:
    all_keys = list(RESPONSE_SECTION_HEADINGS.keys())
    assert ask_router._build_section_override(all_keys) == ""


def test_build_section_override_builds_instruction_for_subset() -> None:
    override = ask_router._build_section_override(["summary", "recommended_process"])

    assert "- Summary" in override
    assert "- Recommended Process" in override
    assert "Reasoning" not in override
    assert "Applicable Policies" not in override


def test_ask_rejects_unknown_section_key(client: TestClient) -> None:
    response = client.post(
        "/api/ask",
        json={"question": "Can a member be suspended?", "sections": ["not-a-real-section"]},
    )
    assert response.status_code == 422


def test_ask_applies_section_override_to_prompt(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, str] = {}

    async def fake_ask_gemini(prompt: str, settings: Settings | None = None) -> str:
        captured["prompt"] = prompt
        return "## Summary\n\nok\n"

    monkeypatch.setattr(ask_router, "ask_gemini", fake_ask_gemini)

    response = client.post(
        "/api/ask",
        json={
            "question": "Can a member be suspended?",
            "sections": ["summary", "recommended_process"],
        },
    )

    assert response.status_code == 200
    assert "RESPONSE SCOPE OVERRIDE" in captured["prompt"]
    assert "- Summary" in captured["prompt"]
    assert "- Recommended Process" in captured["prompt"]
    assert "- Reasoning" not in captured["prompt"]


def test_ask_omits_override_when_no_sections_specified(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, str] = {}

    async def fake_ask_gemini(prompt: str, settings: Settings | None = None) -> str:
        captured["prompt"] = prompt
        return "## Summary\n\nok\n"

    monkeypatch.setattr(ask_router, "ask_gemini", fake_ask_gemini)

    response = client.post("/api/ask", json={"question": "Can a member be suspended?"})

    assert response.status_code == 200
    assert "RESPONSE SCOPE OVERRIDE" not in captured["prompt"]
