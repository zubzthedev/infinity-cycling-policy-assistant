"""Central application configuration, loaded once from the environment."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["local", "production"] = "local"

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.1-flash-lite"
    gemini_timeout_seconds: float = 30.0

    # Firebase (client-side web config is public by design; access control is
    # enforced server-side via verify_id_token + the allow-lists below)
    firebase_project_id: str = ""
    firebase_api_key: str = ""
    firebase_auth_domain: str = ""
    firebase_app_id: str = ""
    google_application_credentials: str | None = None

    # Policies / prompts
    # policy_source selects where the live policy library is loaded from:
    # "local" reads policy_dir on disk (used for local dev, tests, and as
    # the checked-in seed content); "drive" fetches every .md file from a
    # shared Google Drive folder (drive_folder_id) using the same service
    # account credentials as Firebase Admin - this is the source EXCO
    # actually manages via Drive's own sharing/upload/edit UI, and it
    # survives Cloud Run redeploys since Drive storage isn't tied to the
    # container's ephemeral disk.
    policy_source: Literal["local", "drive"] = "local"
    policy_dir: Path = Path("policies")
    drive_folder_id: str = ""
    prompt_dir: Path = Path("prompts")

    # Access control (NoDecode: these arrive as a plain comma-separated
    # string from the environment, not JSON - _parse_email_set does the
    # actual parsing below)
    authorised_users: Annotated[set[str], NoDecode] = set()
    admin_users: Annotated[set[str], NoDecode] = set()

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
        if self.policy_source == "drive" and not self.drive_folder_id:
            raise ValueError("DRIVE_FOLDER_ID must be set when POLICY_SOURCE=drive")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide Settings singleton (cached after first call)."""
    return Settings()


BASE_DIR = Path(__file__).resolve().parent.parent


def resolve_dir(configured: Path) -> Path:
    """Resolve a configured directory (e.g. policy_dir) against the repo root
    if it isn't already absolute."""
    return configured if configured.is_absolute() else BASE_DIR / configured
