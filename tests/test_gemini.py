"""Tests for the Gemini API wrapper: success, timeout, and error mapping."""

from __future__ import annotations

import time

import pytest

from app import gemini
from app.config import Settings


def make_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "gemini_api_key": "test-key",
        "gemini_model": "gemini-2.5-flash",
        "gemini_timeout_seconds": 5.0,
    }
    defaults.update(overrides)
    return Settings(**defaults)


@pytest.mark.asyncio
async def test_ask_gemini_returns_text_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gemini, "_generate", lambda prompt, model: "the answer")

    result = await gemini.ask_gemini("a question", settings=make_settings())

    assert result == "the answer"


@pytest.mark.asyncio
async def test_ask_gemini_raises_timeout_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def slow_generate(prompt: str, model: str) -> str:
        time.sleep(0.5)
        return "too late"

    monkeypatch.setattr(gemini, "_generate", slow_generate)

    with pytest.raises(gemini.GeminiTimeoutError):
        await gemini.ask_gemini("a question", settings=make_settings(gemini_timeout_seconds=0.05))


@pytest.mark.asyncio
async def test_ask_gemini_wraps_unexpected_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_generate(prompt: str, model: str) -> str:
        raise RuntimeError("simulated network failure carrying secret-api-key")

    monkeypatch.setattr(gemini, "_generate", failing_generate)

    with pytest.raises(gemini.GeminiAPIError) as exc_info:
        await gemini.ask_gemini("a question", settings=make_settings())

    # The caller-facing error must never leak the underlying exception text.
    assert "secret-api-key" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_ask_gemini_passes_model_and_prompt_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    def fake_generate(prompt: str, model: str) -> str:
        captured["prompt"] = prompt
        captured["model"] = model
        return "ok"

    monkeypatch.setattr(gemini, "_generate", fake_generate)

    await gemini.ask_gemini(
        "What is the disciplinary process?",
        settings=make_settings(gemini_model="gemini-2.5-flash"),
    )

    assert captured == {
        "prompt": "What is the disciplinary process?",
        "model": "gemini-2.5-flash",
    }
