"""Thin wrapper around the Gemini API used to generate Ask Oufy's answers.

Keeps the SDK call isolated behind a small, mockable function and maps any
failure into one of two exceptions so callers never see raw SDK internals,
stack traces, or the API key.
"""

from __future__ import annotations

import asyncio
import logging

from google import genai
from google.genai import types

from app.config import Settings, get_settings

logger = logging.getLogger("ask_oufy.app")

_client: genai.Client | None = None


class GeminiError(Exception):
    """Base class for all Gemini-related failures."""


class GeminiTimeoutError(GeminiError):
    """Raised when a Gemini request does not complete within the configured timeout."""


class GeminiAPIError(GeminiError):
    """Raised when the Gemini API call fails for any other reason."""


def _get_client() -> genai.Client:
    """Lazily construct the Gemini client, once per process."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options={"timeout": settings.gemini_timeout_seconds},
        )
    return _client


def _generate(prompt: str, model: str) -> str:
    """Synchronous call to the Gemini API. Isolated so tests can mock it directly."""
    client = _get_client()
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.2),
    )
    return response.text or ""


async def ask_gemini(prompt: str, settings: Settings | None = None) -> str:
    """Send a prompt to Gemini and return its raw text answer.

    Raises `GeminiTimeoutError` if the call does not complete within the
    configured timeout, or `GeminiAPIError` for any other failure. Never
    leaks the API key or raw SDK exception internals to the caller.
    """
    settings = settings or get_settings()

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_generate, prompt, settings.gemini_model),
            timeout=settings.gemini_timeout_seconds,
        )
    except TimeoutError as exc:
        logger.error("Gemini request timed out after %.1fs", settings.gemini_timeout_seconds)
        raise GeminiTimeoutError("Ask Oufy did not receive a response in time.") from exc
    except Exception as exc:
        logger.error("Gemini request failed: %s", exc)
        raise GeminiAPIError("Ask Oufy could not get an answer from Gemini.") from exc
