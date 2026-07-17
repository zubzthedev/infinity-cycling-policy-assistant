"""Shared Pydantic request/response models for Ask Oufy's API."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

# The response sections a user may opt in/out of via the Ask Oufy front end,
# mapped to the exact heading text used in prompts/response_rules.md and in
# Gemini's output - ask.py uses this same mapping to build a per-request
# instruction telling Gemini which sections to include.
RESPONSE_SECTION_HEADINGS: dict[str, str] = {
    "applicable_policies": "Applicable Policies",
    "summary": "Summary",
    "reasoning": "Reasoning",
    "recommended_process": "Recommended Process",
    "policy_references": "Policy References",
}


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    # None (or every key present) means "include everything" - the default,
    # unmodified response format. Omitting keys asks Gemini to leave out
    # those sections for this specific question only.
    sections: list[str] | None = None

    @field_validator("sections")
    @classmethod
    def _validate_sections(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        unknown = set(value) - RESPONSE_SECTION_HEADINGS.keys()
        if unknown:
            raise ValueError(f"Unknown response section(s): {', '.join(sorted(unknown))}")
        return value


class PolicyReferenceModel(BaseModel):
    text: str
    policy_slug: str | None = None
    section_slug: str | None = None


class AskResponse(BaseModel):
    answer_html: str
    answer_markdown: str
    policy_references: list[PolicyReferenceModel]


class SectionModel(BaseModel):
    slug: str
    heading: str
    level: int


class PolicyDocumentModel(BaseModel):
    slug: str
    title: str
    html: str
    sections: list[SectionModel]


class PolicyLibraryResponse(BaseModel):
    documents: list[PolicyDocumentModel]


class PolicyStatusModel(BaseModel):
    slug: str
    filename: str
    title: str
    mtime: float


class PolicyLoadErrorModel(BaseModel):
    filename: str
    error: str


class AdminStatusResponse(BaseModel):
    environment: str
    gemini_model: str
    policy_source: str
    prompts_loaded: bool
    policies: list[PolicyStatusModel]
    policy_load_errors: list[PolicyLoadErrorModel]


class PromptsModel(BaseModel):
    system: str = Field(max_length=20_000)
    response_rules: str = Field(max_length=20_000)
    examples: str = Field(max_length=20_000)
