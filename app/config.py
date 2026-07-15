"""Central application configuration, loaded once from the environment."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["local", "production"] = "local"

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_timeout_seconds: float = 30.0

    # Firebase
    firebase_project_id: str = ""
    google_application_credentials: str | None = None

    # Policies / prompts
    policy_dir: Path = Path("policies")
    prompt_dir: Path = Path("prompts")

    # Access control
    authorised_users: set[str] = set()
    admin_users: set[str] = set()

    # Logging
    log_questions: bool = True
    log_responses: bool = False

    # Rate limiting
    rate_limit_per_minute: int = 10

    # Feature flags
    enable_admin_ui: bool = True

    @field_validator("authorised_users", "admin_users", mode="before")
    @classmethod
    def _parse_email_set(cls, value: object) -> set[str]:
        if isinstance(value, str):
            return {email.strip().lower() for email in value.split(",") if email.strip()}
        if isinstance(value, set | list | tuple):
            return {str(email).strip().lower() for email in value if str(email).strip()}
        return set()

    @model_validator(mode="after")
    def _validate_production_requirements(self) -> Settings:
        if self.environment == "production":
            if not self.gemini_api_key:
                raise ValueError("GEMINI_API_KEY must be set in production")
            if not self.authorised_users:
                raise ValueError("AUTHORISED_USERS must be set in production")
        if self.admin_users - self.authorised_users:
            raise ValueError("Every admin user must also be an authorised user")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide Settings singleton (cached after first call)."""
    return Settings()
