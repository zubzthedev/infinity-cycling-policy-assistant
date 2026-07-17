"""Loads, caches, and serves the club's Markdown policy library.

Policies can be loaded from two sources, selected by `Settings.policy_source`:

- "local": every `.md` file in `policy_dir` on disk. Used for local dev,
  tests, and as the checked-in seed content.
- "drive": every `.md` file in a shared Google Drive folder, fetched via
  the Drive API using the same service account credentials as Firebase
  Admin. This is the source EXCO actually manages day to day - Drive's own
  sharing/upload/edit UI replaces a custom admin upload form, and Drive
  storage survives Cloud Run redeploys since it isn't tied to the
  container's ephemeral disk.

Either way, documents are loaded once (at startup, or on an explicit
admin-triggered reload) and rendered to HTML up front. Requests only ever
read the in-memory store - no I/O or Markdown parsing happens per request.
A reload builds a brand-new store off to the side and then swaps a single
module-level reference, so concurrent readers never observe a half-built
store.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import google.auth
import markdown as markdown_lib
from google.oauth2 import service_account
from googleapiclient.discovery import build

from app.config import Settings, resolve_dir

logger = logging.getLogger("ask_oufy.app")

_HEADING_RE = re.compile(r"^#\s+(.*)$", re.MULTILINE)
_EXCLUDED_FILENAMES = {"readme.md"}
_DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"


def slugify(text: str) -> str:
    """Convert arbitrary text into a lowercase, hyphenated, URL-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower())
    return slug.strip("-")


@dataclass(frozen=True)
class Section:
    """A heading within a policy document, addressable via anchor link."""

    slug: str
    heading: str
    level: int


@dataclass(frozen=True)
class Policy:
    """A single loaded, rendered policy document."""

    slug: str
    title: str
    filename: str
    raw_markdown: str
    html: str
    sections: tuple[Section, ...]
    mtime: float


@dataclass(frozen=True)
class PolicyLoadError:
    """Records why a document could not be loaded."""

    filename: str
    error: str


@dataclass(frozen=True)
class PolicyStore:
    """An immutable snapshot of every successfully loaded policy document."""

    policies: dict[str, Policy]
    order: tuple[str, ...]
    errors: tuple[PolicyLoadError, ...]

    def get(self, slug: str) -> Policy | None:
        return self.policies.get(slug)

    def __iter__(self):
        for slug in self.order:
            yield self.policies[slug]

    def __len__(self) -> int:
        return len(self.order)


_EMPTY_STORE = PolicyStore(policies={}, order=(), errors=())


def _derive_title(markdown_text: str, fallback: str) -> str:
    match = _HEADING_RE.search(markdown_text)
    if match:
        return match.group(1).strip()
    return fallback


def _extract_sections_and_rewrite_html(
    doc_slug: str, html: str, md: markdown_lib.Markdown
) -> tuple[tuple[Section, ...], str]:
    """Flatten the `toc` extension's heading tree and prefix every anchor id
    with the document's slug (e.g. `6-2-...` -> `constitution--6-2-...`).

    The Policy Library renders every document on a single page, so heading
    ids must be globally unique across documents - without this, two policies
    with a similarly-worded heading would collide on the same anchor id.
    """
    sections: list[Section] = []

    def walk(tokens: list[dict]) -> None:
        nonlocal html
        for token in tokens:
            original_id = token["id"]
            prefixed_id = f"{doc_slug}--{original_id}"
            html = html.replace(f'id="{original_id}"', f'id="{prefixed_id}"', 1)
            sections.append(Section(slug=prefixed_id, heading=token["name"], level=token["level"]))
            walk(token.get("children", []))

    walk(getattr(md, "toc_tokens", []))
    return tuple(sections), html


def _build_policy(filename: str, raw: str, mtime: float) -> Policy:
    """Parse raw Markdown text into a rendered Policy document."""
    stem = Path(filename).stem
    slug = slugify(stem)
    fallback_title = stem.replace("_", " ").replace("-", " ").title()
    title = _derive_title(raw, fallback=fallback_title)

    md = markdown_lib.Markdown(extensions=["tables", "toc", "fenced_code", "sane_lists"])
    html = md.convert(raw)
    sections, html = _extract_sections_and_rewrite_html(slug, html, md)

    return Policy(
        slug=slug,
        title=title,
        filename=filename,
        raw_markdown=raw,
        html=html,
        sections=sections,
        mtime=mtime,
    )


def _build_store(sources: Iterable[tuple[str, Callable[[], tuple[str, float]]]]) -> PolicyStore:
    """Build a PolicyStore from (filename, loader) pairs.

    `loader()` returns (raw_text, mtime) and is only called (and only
    allowed to raise) inside this function's try/except, so a single
    malformed or unreachable document is logged and skipped rather than
    aborting the whole load - shared by both the local-disk and Drive
    loaders below.
    """
    policies: dict[str, Policy] = {}
    order: list[str] = []
    errors: list[PolicyLoadError] = []

    for filename, loader in sources:
        if filename.lower() in _EXCLUDED_FILENAMES:
            continue

        try:
            raw, mtime = loader()
            policy = _build_policy(filename, raw, mtime)
        except Exception as exc:  # noqa: BLE001 - any bad document must be skipped, not fatal
            logger.error("Failed to load policy %s: %s", filename, exc)
            errors.append(PolicyLoadError(filename=filename, error=str(exc)))
            continue

        if policy.slug in policies:
            logger.error(
                "Duplicate policy slug %r from %s (already loaded from %s)",
                policy.slug,
                filename,
                policies[policy.slug].filename,
            )
            errors.append(
                PolicyLoadError(filename=filename, error=f"duplicate slug '{policy.slug}'")
            )
            continue

        policies[policy.slug] = policy
        order.append(policy.slug)

    return PolicyStore(policies=policies, order=tuple(order), errors=tuple(errors))


def load_policies(policy_dir: Path) -> PolicyStore:
    """Load every Markdown policy document from `policy_dir` on local disk."""
    if not policy_dir.is_dir():
        logger.error("Policy directory does not exist: %s", policy_dir)
        return PolicyStore(
            policies={},
            order=(),
            errors=(PolicyLoadError(filename=str(policy_dir), error="directory not found"),),
        )

    def make_loader(path: Path) -> Callable[[], tuple[str, float]]:
        return lambda: (path.read_text(encoding="utf-8"), path.stat().st_mtime)

    sources = [(path.name, make_loader(path)) for path in sorted(policy_dir.glob("*.md"))]
    return _build_store(sources)


_drive_service: object | None = None


def _get_drive_service(credentials_path: str) -> object:
    """Lazily build the Drive API client, once per process.

    With a credentials_path (local dev, via GOOGLE_APPLICATION_CREDENTIALS),
    loads that service account key file directly. Without one, falls back
    to Application Default Credentials - e.g. Cloud Run running as the
    service account itself, which needs no key file at all and is the
    more secure production setup.
    """
    global _drive_service
    if _drive_service is None:
        if credentials_path:
            credentials = service_account.Credentials.from_service_account_file(
                credentials_path, scopes=[_DRIVE_READONLY_SCOPE]
            )
        else:
            credentials, _ = google.auth.default(scopes=[_DRIVE_READONLY_SCOPE])
        _drive_service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    return _drive_service


def _list_drive_markdown_files(folder_id: str, credentials_path: str) -> list[dict]:
    """List every `.md` file directly inside the given Drive folder.

    Isolated so tests can mock the Drive API without real credentials.
    """
    service = _get_drive_service(credentials_path)
    query = f"'{folder_id}' in parents and trashed = false"
    response = (
        service.files()  # type: ignore[attr-defined]
        .list(q=query, fields="files(id, name, mimeType, modifiedTime)", pageSize=1000)
        .execute()
    )
    return [f for f in response.get("files", []) if f["name"].lower().endswith(".md")]


def _fetch_drive_file_content(file_id: str, credentials_path: str) -> str:
    """Download a Drive file's raw content as text.

    Isolated so tests can mock the Drive API without real credentials.
    """
    service = _get_drive_service(credentials_path)
    content = service.files().get_media(fileId=file_id).execute()  # type: ignore[attr-defined]
    return content.decode("utf-8") if isinstance(content, bytes) else content


def load_policies_from_drive(folder_id: str, credentials_path: str) -> PolicyStore:
    """Load every Markdown policy document from a shared Google Drive folder.

    Uses the same service account as Firebase Admin, scoped read-only to
    Drive. The folder must be shared with that service account's email
    (the `client_email` field in the credentials JSON). A Drive outage or
    misconfiguration is logged and yields an empty-with-errors store rather
    than crashing the app.
    """
    try:
        files = _list_drive_markdown_files(folder_id, credentials_path)
    except Exception as exc:  # noqa: BLE001 - Drive being unreachable must not crash the app
        logger.error("Failed to list Drive folder %s: %s", folder_id, exc)
        return PolicyStore(
            policies={},
            order=(),
            errors=(
                PolicyLoadError(filename=folder_id, error=f"could not list Drive folder: {exc}"),
            ),
        )

    def make_loader(file_meta: dict) -> Callable[[], tuple[str, float]]:
        def loader() -> tuple[str, float]:
            raw = _fetch_drive_file_content(file_meta["id"], credentials_path)
            modified = file_meta.get("modifiedTime", "")
            mtime = (
                datetime.fromisoformat(modified.replace("Z", "+00:00")).timestamp()
                if modified
                else 0.0
            )
            return raw, mtime

        return loader

    sources = [(f["name"], make_loader(f)) for f in files]
    return _build_store(sources)


_lock = threading.Lock()
_store: PolicyStore = _EMPTY_STORE


def get_store() -> PolicyStore:
    """Return the current, already-loaded policy store (no I/O)."""
    return _store


def _swap_store(new_store: PolicyStore, source_desc: str) -> PolicyStore:
    """Atomically install a freshly-built store as the current one.

    The new store is fully built before this is called, so a concurrent
    `get_store()` never sees a partially built store. The lock only
    serialises concurrent *reload* calls (e.g. two admin requests).
    """
    global _store
    with _lock:
        _store = new_store
    logger.info(
        "Loaded %d polic%s from %s (%d error%s)",
        len(new_store),
        "y" if len(new_store) == 1 else "ies",
        source_desc,
        len(new_store.errors),
        "" if len(new_store.errors) == 1 else "s",
    )
    return new_store


def reload_store(policy_dir: Path) -> PolicyStore:
    """Reload the policy store from local disk and swap it in."""
    return _swap_store(load_policies(policy_dir), str(policy_dir))


def reload_store_from_drive(folder_id: str, credentials_path: str) -> PolicyStore:
    """Reload the policy store from Google Drive and swap it in."""
    return _swap_store(
        load_policies_from_drive(folder_id, credentials_path), f"Drive folder {folder_id}"
    )


def reload_policies(settings: Settings) -> PolicyStore:
    """Reload the policy store from whichever source is configured."""
    if settings.policy_source == "drive":
        return reload_store_from_drive(
            settings.drive_folder_id, settings.google_application_credentials or ""
        )
    return reload_store(resolve_dir(settings.policy_dir))
