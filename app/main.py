"""Ask Oufy — FastAPI application entry point."""

from __future__ import annotations

from fastapi import FastAPI

from app.config import get_settings

settings = get_settings()

app = FastAPI(title="Ask Oufy")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness/readiness probe used by Cloud Run and local checks."""
    return {"status": "ok", "environment": settings.environment}
