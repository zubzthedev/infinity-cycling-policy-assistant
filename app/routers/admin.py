"""Admin-only endpoints: view status, reload, and edit the prompt framework.

Like the Policy Library, /admin is a public HTML shell with no sensitive
data embedded - a plain page navigation can't carry a Bearer token, so real
authorisation is enforced here, on every API call, via require_admin.

Policies themselves are managed outside this app: either by editing the
checked-in files under policies/ (policy_source=local) or, day to day, by
uploading/editing/deleting .md files directly in a shared Google Drive
folder (policy_source=drive) - Drive's own sharing and edit history already
cover what a custom upload/delete UI would otherwise need to reimplement.

Prompts are different: they're tuned by whoever is engineering Ask Oufy's
behaviour, not by EXCO at large, so a lightweight in-app editor (below)
makes more sense than routing through Drive. Like policy uploads used to
be, prompt edits here are written to local disk, which does NOT persist
across a Cloud Run redeploy - fine for local development and iteration,
but worth remembering before relying on it in production.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app import policies, prompts
from app.auth import AuthenticatedUser, require_admin
from app.config import Settings, get_settings, resolve_dir
from app.models.schemas import (
    AdminStatusResponse,
    PolicyLoadErrorModel,
    PolicyStatusModel,
    PromptsModel,
)

logger = logging.getLogger("ask_oufy.app")

router = APIRouter(prefix="/api/admin")


def _status_response(settings: Settings) -> AdminStatusResponse:
    store = policies.get_store()
    prompt_set = prompts.get_prompts()
    return AdminStatusResponse(
        environment=settings.environment,
        gemini_model=settings.gemini_model,
        policy_source=settings.policy_source,
        prompts_loaded=bool(prompt_set.system),
        policies=[
            PolicyStatusModel(slug=p.slug, filename=p.filename, title=p.title, mtime=p.mtime)
            for p in store
        ],
        policy_load_errors=[
            PolicyLoadErrorModel(filename=e.filename, error=e.error) for e in store.errors
        ],
    )


@router.get("/status", response_model=AdminStatusResponse)
def get_status(
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> AdminStatusResponse:
    """View loaded policies/prompts, load errors, and current configuration."""
    return _status_response(settings)


@router.post("/reload", response_model=AdminStatusResponse)
def reload_all(
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> AdminStatusResponse:
    """Reload policies (from Drive or local disk, per POLICY_SOURCE) and
    prompts, without restarting the application."""
    policies.reload_policies(settings)
    prompts.reload_prompts(resolve_dir(settings.prompt_dir))
    logger.info("Policies and prompts reloaded by admin %s", user.email)
    return _status_response(settings)


@router.get("/prompts", response_model=PromptsModel)
def get_prompts_content(
    user: AuthenticatedUser = Depends(require_admin),
) -> PromptsModel:
    """Return the current prompt framework content for editing."""
    prompt_set = prompts.get_prompts()
    return PromptsModel(
        system=prompt_set.system,
        response_rules=prompt_set.response_rules,
        examples=prompt_set.examples,
    )


@router.put("/prompts", response_model=AdminStatusResponse)
def update_prompts_content(
    payload: PromptsModel,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> AdminStatusResponse:
    """Overwrite system.md/response_rules.md/examples.md and reload them."""
    prompt_dir = resolve_dir(settings.prompt_dir)
    prompt_dir.mkdir(parents=True, exist_ok=True)
    (prompt_dir / "system.md").write_text(payload.system, encoding="utf-8")
    (prompt_dir / "response_rules.md").write_text(payload.response_rules, encoding="utf-8")
    (prompt_dir / "examples.md").write_text(payload.examples, encoding="utf-8")
    prompts.reload_prompts(prompt_dir)
    logger.info("Prompts updated by admin %s", user.email)
    return _status_response(settings)
