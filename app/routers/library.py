"""GET /api/policies - serves the cached Policy Library content as JSON.

The actual `/library` page is a public, unauthenticated HTML shell (see
templates/library.html) - it contains no policy content. This endpoint is
where real authorisation is enforced: the browser has no way to attach a
Bearer token to a plain page navigation, so the library's content can only
be fetched by client-side JS that already holds a valid Firebase ID token.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import AuthenticatedUser, get_current_user
from app.models.schemas import PolicyDocumentModel, PolicyLibraryResponse, SectionModel
from app.policies import get_store

router = APIRouter()


@router.get("/api/policies", response_model=PolicyLibraryResponse)
def list_policies(
    user: AuthenticatedUser = Depends(get_current_user),
) -> PolicyLibraryResponse:
    """Return every loaded policy document's pre-rendered HTML and section index.

    No Markdown parsing happens here - every document was already rendered
    to HTML once at load time (see app/policies.py); this only serialises
    the already-cached data.
    """
    store = get_store()
    documents = [
        PolicyDocumentModel(
            slug=policy.slug,
            title=policy.title,
            html=policy.html,
            sections=[
                SectionModel(slug=section.slug, heading=section.heading, level=section.level)
                for section in policy.sections
            ],
        )
        for policy in store
    ]
    return PolicyLibraryResponse(documents=documents)
