"""POST /api/ask - Ask Oufy's core question-answering endpoint."""

from __future__ import annotations

import re
from dataclasses import dataclass

import markdown as markdown_lib
from fastapi import APIRouter, Depends, HTTPException

from app.auth import AuthenticatedUser
from app.config import Settings, get_settings
from app.gemini import GeminiAPIError, GeminiTimeoutError, ask_gemini
from app.models.schemas import AskRequest, AskResponse, PolicyReferenceModel
from app.policies import PolicyStore, get_store
from app.prompts import build_prompt, get_prompts
from app.rate_limit import rate_limit

router = APIRouter()

_REFERENCES_HEADING_RE = re.compile(r"^##\s*Policy References\s*$", re.MULTILINE | re.IGNORECASE)
_NEXT_HEADING_RE = re.compile(r"^##\s", re.MULTILINE)
_LIST_ITEM_RE = re.compile(r"^[*-]\s+(.*)$", re.MULTILINE)
_SECTION_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)*)")


@dataclass(frozen=True)
class PolicyReference:
    """A single citation extracted from a Gemini answer's Policy References section."""

    text: str
    policy_slug: str | None
    section_slug: str | None


def extract_policy_references(answer_text: str, store: PolicyStore) -> list[PolicyReference]:
    """Best-effort extraction of cited policy/section pairs from a Gemini answer.

    This parsing is purely an enhancement for audit logging and Policy
    Library deep-linking - if the "## Policy References" heading is
    missing, or a line can't be matched to a known document or section, the
    raw answer is still returned unchanged by the caller; nothing here ever
    blocks rendering the answer.
    """
    heading_match = _REFERENCES_HEADING_RE.search(answer_text)
    if not heading_match:
        return []

    remainder = answer_text[heading_match.end() :]
    next_heading = _NEXT_HEADING_RE.search(remainder)
    block = remainder[: next_heading.start()] if next_heading else remainder

    return [_match_reference(line.strip(), store) for line in _LIST_ITEM_RE.findall(block)]


def _match_reference(line: str, store: PolicyStore) -> PolicyReference:
    lower_line = line.lower()
    matched_policy = None
    for policy in store:
        if policy.title.lower() in lower_line:
            if matched_policy is None or len(policy.title) > len(matched_policy.title):
                matched_policy = policy

    if matched_policy is None:
        return PolicyReference(text=line, policy_slug=None, section_slug=None)

    section_slug = None
    number_match = _SECTION_NUMBER_RE.search(line)
    if number_match:
        number = number_match.group(1)
        for section in matched_policy.sections:
            if section.heading.startswith(number):
                section_slug = section.slug
                break

    return PolicyReference(text=line, policy_slug=matched_policy.slug, section_slug=section_slug)


@router.post("/api/ask", response_model=AskResponse)
async def ask(
    request: AskRequest,
    user: AuthenticatedUser = Depends(rate_limit),
    settings: Settings = Depends(get_settings),
) -> AskResponse:
    """Answer a governance question using only the loaded policy library."""
    store = get_store()
    prompt = build_prompt(request.question, store, get_prompts())

    try:
        answer_markdown = await ask_gemini(prompt, settings=settings)
    except GeminiTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except GeminiAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    references = extract_policy_references(answer_markdown, store)
    answer_html = markdown_lib.markdown(
        answer_markdown, extensions=["tables", "sane_lists", "fenced_code"]
    )

    return AskResponse(
        answer_html=answer_html,
        answer_markdown=answer_markdown,
        policy_references=[
            PolicyReferenceModel(
                text=ref.text, policy_slug=ref.policy_slug, section_slug=ref.section_slug
            )
            for ref in references
        ],
    )
