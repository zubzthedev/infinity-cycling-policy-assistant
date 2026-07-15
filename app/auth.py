"""Firebase-based authentication and allow-list authorisation for Ask Oufy.

Clients send a Firebase ID token as an ``Authorization: Bearer <token>``
header (never a cookie), obtained client-side after Google Sign-In. This
module verifies that token server-side and checks the resulting email
address against the configured allow-lists. Because the token is never
stored in a cookie, it is never sent automatically by the browser, so
classic CSRF protection does not apply here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import firebase_admin
from fastapi import Depends, HTTPException, Request, status
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials
from firebase_admin import exceptions as firebase_exceptions

from app.config import Settings, get_settings

_firebase_app: firebase_admin.App | None = None


def _get_firebase_app() -> firebase_admin.App:
    """Lazily initialise the Firebase Admin app, once per process."""
    global _firebase_app
    if _firebase_app is None:
        settings = get_settings()
        if settings.google_application_credentials:
            cred = credentials.Certificate(settings.google_application_credentials)
            _firebase_app = firebase_admin.initialize_app(cred)
        else:
            # Falls back to Application Default Credentials, e.g. the Cloud
            # Run service identity in production.
            _firebase_app = firebase_admin.initialize_app()
    return _firebase_app


def _verify_id_token(token: str) -> dict[str, Any]:
    """Verify a Firebase ID token, raising on failure.

    Kept as a thin, separately-mockable function so tests can simulate
    Firebase's verification result without needing real credentials.
    """
    return firebase_auth.verify_id_token(token, app=_get_firebase_app(), check_revoked=True)


@dataclass(frozen=True)
class AuthenticatedUser:
    """The authenticated, allow-listed user making the current request."""

    uid: str
    email: str
    is_admin: bool


def _extract_bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization")
    if not header or not header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header.",
        )
    return header.removeprefix("Bearer ").strip()


def get_current_user(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> AuthenticatedUser:
    """FastAPI dependency: verify the ID token and enforce the allow-list."""
    token = _extract_bearer_token(request)

    try:
        decoded = _verify_id_token(token)
    except (firebase_exceptions.FirebaseError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired sign-in token.",
        ) from exc

    email = str(decoded.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign-in token did not include an email address.",
        )

    if email not in settings.authorised_users:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not authorised to access Ask Oufy.",
        )

    return AuthenticatedUser(
        uid=str(decoded["uid"]),
        email=email,
        is_admin=email in settings.admin_users,
    )


def require_admin(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    """FastAPI dependency: additionally require administrator access."""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires administrator access.",
        )
    return user
