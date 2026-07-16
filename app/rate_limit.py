"""A minimal in-memory rate limiter for Ask Oufy's API endpoints.

Deliberately not distributed: Cloud Run runs this app with very low
concurrency for a small committee tool (scale-to-zero, 0-2 instances), so
per-instance in-memory state is an acceptable trade-off. If traffic or
multi-instance concurrency ever grows, this would need to move to a shared
store (e.g. Redis or Firestore) - a documented future enhancement, not
something to build preemptively.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import Depends, HTTPException, status

from app.auth import AuthenticatedUser, get_current_user
from app.config import Settings, get_settings

_WINDOW_SECONDS = 60.0

_lock = Lock()
_requests: dict[str, deque[float]] = defaultdict(deque)


def _check_rate_limit(key: str, limit_per_minute: int) -> None:
    now = time.monotonic()
    window_start = now - _WINDOW_SECONDS

    with _lock:
        timestamps = _requests[key]
        while timestamps and timestamps[0] < window_start:
            timestamps.popleft()

        if len(timestamps) >= limit_per_minute:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please wait a moment and try again.",
            )

        timestamps.append(now)


def rate_limit(
    user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedUser:
    """FastAPI dependency: authenticate, then enforce a per-user rate limit."""
    _check_rate_limit(user.email, settings.rate_limit_per_minute)
    return user
