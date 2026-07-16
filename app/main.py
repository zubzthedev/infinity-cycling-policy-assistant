"""Ask Oufy — FastAPI application entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import policies, prompts
from app.auth import AuthenticatedUser, get_current_user
from app.config import BASE_DIR, get_settings, resolve_dir
from app.routers import admin, ask, library

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    policies.reload_store(resolve_dir(settings.policy_dir))
    prompts.reload_prompts(resolve_dir(settings.prompt_dir))
    yield


app = FastAPI(title="Ask Oufy", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
app.include_router(ask.router)
app.include_router(library.router)
if settings.enable_admin_ui:
    app.include_router(admin.router)


def _firebase_config() -> dict[str, str]:
    return {
        "apiKey": settings.firebase_api_key,
        "authDomain": settings.firebase_auth_domain,
        "projectId": settings.firebase_project_id,
        "appId": settings.firebase_app_id,
    }


@app.get("/healthz")
def healthz() -> dict[str, object]:
    """Liveness/readiness probe used by Cloud Run and local checks."""
    store = policies.get_store()
    prompt_set = prompts.get_prompts()
    return {
        "status": "ok",
        "environment": settings.environment,
        "policies_loaded": len(store),
        "policy_load_errors": len(store.errors),
        "prompts_loaded": bool(prompt_set.system),
    }


@app.get("/", response_class=HTMLResponse)
def index_page(request: Request) -> HTMLResponse:
    """Serve the Ask Oufy landing page (auth is enforced by /api/ask, not here)."""
    return templates.TemplateResponse(
        request, "index.html", {"firebase_config": _firebase_config()}
    )


@app.get("/library", response_class=HTMLResponse)
def library_page(request: Request) -> HTMLResponse:
    """Serve the Policy Library page shell (content is fetched client-side
    from GET /api/policies, which is where auth is actually enforced - a
    plain page navigation can't carry a Bearer token)."""
    return templates.TemplateResponse(
        request, "library.html", {"firebase_config": _firebase_config()}
    )


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request) -> HTMLResponse:
    """Serve the Administration page shell (content and actions go through
    the protected /api/admin/* endpoints, same reasoning as /library)."""
    return templates.TemplateResponse(
        request, "admin.html", {"firebase_config": _firebase_config()}
    )


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    """Serve the Google Sign-In page with Firebase's public web config."""
    return templates.TemplateResponse(
        request, "login.html", {"firebase_config": _firebase_config()}
    )


@app.get("/api/whoami")
def whoami(user: AuthenticatedUser = Depends(get_current_user)) -> dict[str, object]:
    """Minimal protected route proving the 401/403/200 auth paths work."""
    return {"email": user.email, "is_admin": user.is_admin}
