"""Shared Pydantic request/response models for Ask Oufy's API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


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
