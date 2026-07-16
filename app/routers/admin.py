"""Admin-only endpoints: view status, upload/replace/delete policies, reload.

Like the Policy Library, /admin is a public HTML shell with no sensitive
data embedded - a plain page navigation can't carry a Bearer token, so real
authorisation is enforced here, on every API call, via require_admin.

There is no versioning or rollback for uploaded policies in this version -
the checked-in repository content is the source of truth; admin uploads are
intended for the current deployment/testing cycle. Uploaded files also
don't persist across a Cloud Run redeploy, since the container filesystem
is ephemeral (documented in the README).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app import policies, prompts
from app.auth import AuthenticatedUser, require_admin
from app.config import Settings, get_settings, resolve_dir
from app.models.schemas import AdminStatusResponse, PolicyLoadErrorModel, PolicyStatusModel

logger = logging.getLogger("ask_oufy.app")

router = APIRouter(prefix="/api/admin")

_MAX_UPLOAD_BYTES = 500_000
_SAFE_STEM_RE = re.compile(r"[^a-z0-9_.-]+")


def _sanitize_filename(filename: str) -> str:
    """Derive a safe, flat `.md` filename from a user-supplied upload name.

    Discards any directory components (defeating path traversal), lowercases,
    and replaces anything outside a small safe character set.
    """
    name = Path(filename).name.lower().strip()
    if not name.endswith(".md"):
        raise ValueError("Only .md files are allowed.")
    stem = _SAFE_STEM_RE.sub("-", name[:-3]).strip("-.")
    if not stem:
        raise ValueError("Filename is empty after sanitisation.")
    return f"{stem}.md"


def _status_response(settings: Settings) -> AdminStatusResponse:
    store = policies.get_store()
    prompt_set = prompts.get_prompts()
    return AdminStatusResponse(
        environment=settings.environment,
        gemini_model=settings.gemini_model,
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
    """Reload policies and prompts from disk without restarting the app."""
    policies.reload_store(resolve_dir(settings.policy_dir))
    prompts.reload_prompts(resolve_dir(settings.prompt_dir))
    logger.info("Policies and prompts reloaded by admin %s", user.email)
    return _status_response(settings)


@router.post("/policies", response_model=AdminStatusResponse)
async def upload_policy(
    file: UploadFile,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> AdminStatusResponse:
    """Upload a new policy, or replace an existing one with the same filename."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    try:
        safe_filename = _sanitize_filename(file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 500KB size limit.")

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded text.") from exc

    policy_dir = resolve_dir(settings.policy_dir)
    policy_dir.mkdir(parents=True, exist_ok=True)
    (policy_dir / safe_filename).write_text(text, encoding="utf-8")

    policies.reload_store(policy_dir)
    logger.info("Policy %s uploaded by admin %s", safe_filename, user.email)
    return _status_response(settings)


@router.delete("/policies/{slug}", response_model=AdminStatusResponse)
def delete_policy(
    slug: str,
    user: AuthenticatedUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> AdminStatusResponse:
    """Delete a currently-loaded policy by its slug."""
    store = policies.get_store()
    policy = store.get(slug)
    if policy is None:
        raise HTTPException(status_code=404, detail="No loaded policy with that slug.")

    policy_dir = resolve_dir(settings.policy_dir)
    (policy_dir / policy.filename).unlink(missing_ok=True)

    policies.reload_store(policy_dir)
    logger.info("Policy %s deleted by admin %s", policy.filename, user.email)
    return _status_response(settings)
