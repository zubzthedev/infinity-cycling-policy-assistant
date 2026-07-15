"""Ask Oufy — FastAPI application entry point."""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.auth import AuthenticatedUser, get_current_user, require_admin
from app.config import get_settings

BASE_DIR = Path(__file__).resolve().parent.parent

settings = get_settings()

app = FastAPI(title="Ask Oufy")

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness/readiness probe used by Cloud Run and local checks."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    """Serve the Google Sign-In page with Firebase's public web config."""
    firebase_config = {
        "apiKey": settings.firebase_api_key,
        "authDomain": settings.firebase_auth_domain,
        "projectId": settings.firebase_project_id,
        "appId": settings.firebase_app_id,
    }
    return templates.TemplateResponse(
        request, "login.html", {"firebase_config": firebase_config}
    )


@app.get("/api/whoami")
def whoami(user: AuthenticatedUser = Depends(get_current_user)) -> dict[str, object]:
    """Minimal protected route proving the 401/403/200 auth paths work."""
    return {"email": user.email, "is_admin": user.is_admin}


@app.get("/api/admin/ping")
def admin_ping(user: AuthenticatedUser = Depends(require_admin)) -> dict[str, str]:
    """Minimal admin-only route proving the require_admin dependency works."""
    return {"status": "ok", "admin": user.email}
