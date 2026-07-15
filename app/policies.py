"""Loads, caches, and serves the club's Markdown policy library.

All policy documents are read from disk once (at startup, or on an explicit
admin-triggered reload) and rendered to HTML up front. Requests only ever
read the in-memory store - no file I/O or Markdown parsing happens per
request. A reload builds a brand-new store off to the side and then swaps
a single module-level reference, so concurrent readers never observe a
half-built store.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path

import markdown as markdown_lib

logger = logging.getLogger("ask_oufy.app")

_HEADING_RE = re.compile(r"^#\s+(.*)$", re.MULTILINE)
_EXCLUDED_FILENAMES = {"readme.md"}


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
    """Records why a file in the policy directory could not be loaded."""

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


def _extract_sections(md: markdown_lib.Markdown) -> tuple[Section, ...]:
    """Flatten the `toc` extension's nested heading tree into a flat list."""
    sections: list[Section] = []

    def walk(tokens: list[dict]) -> None:
        for token in tokens:
            sections.append(
                Section(slug=token["id"], heading=token["name"], level=token["level"])
            )
            walk(token.get("children", []))

    walk(getattr(md, "toc_tokens", []))
    return tuple(sections)


def _load_one(path: Path) -> Policy:
    raw = path.read_text(encoding="utf-8")
    slug = slugify(path.stem)
    fallback_title = path.stem.replace("_", " ").replace("-", " ").title()
    title = _derive_title(raw, fallback=fallback_title)

    md = markdown_lib.Markdown(extensions=["tables", "toc", "fenced_code", "sane_lists"])
    html = md.convert(raw)
    sections = _extract_sections(md)

    return Policy(
        slug=slug,
        title=title,
        filename=path.name,
        raw_markdown=raw,
        html=html,
        sections=sections,
        mtime=path.stat().st_mtime,
    )


def load_policies(policy_dir: Path) -> PolicyStore:
    """Load every Markdown policy document from `policy_dir` into a fresh store.

    A single malformed or unreadable file is logged and skipped rather than
    aborting the load - one bad document must never take down the whole
    policy library.
    """
    if not policy_dir.is_dir():
        logger.error("Policy directory does not exist: %s", policy_dir)
        return PolicyStore(
            policies={},
            order=(),
            errors=(PolicyLoadError(filename=str(policy_dir), error="directory not found"),),
        )

    policies: dict[str, Policy] = {}
    order: list[str] = []
    errors: list[PolicyLoadError] = []

    for path in sorted(policy_dir.glob("*.md")):
        if path.name.lower() in _EXCLUDED_FILENAMES:
            continue

        try:
            policy = _load_one(path)
        except Exception as exc:  # noqa: BLE001 - any bad file must be skipped, not fatal
            logger.error("Failed to load policy %s: %s", path.name, exc)
            errors.append(PolicyLoadError(filename=path.name, error=str(exc)))
            continue

        if policy.slug in policies:
            logger.error(
                "Duplicate policy slug %r from %s (already loaded from %s)",
                policy.slug,
                path.name,
                policies[policy.slug].filename,
            )
            errors.append(
                PolicyLoadError(filename=path.name, error=f"duplicate slug '{policy.slug}'")
            )
            continue

        policies[policy.slug] = policy
        order.append(policy.slug)

    return PolicyStore(policies=policies, order=tuple(order), errors=tuple(errors))


_lock = threading.Lock()
_store: PolicyStore = _EMPTY_STORE


def get_store() -> PolicyStore:
    """Return the current, already-loaded policy store (no I/O)."""
    return _store


def reload_store(policy_dir: Path) -> PolicyStore:
    """Rebuild the policy store from disk and atomically swap it in.

    The new store is fully built before the module-level reference is
    replaced, so a concurrent `get_store()` call never sees a partially
    built store. The lock only serialises concurrent *reload* calls
    (e.g. two admin requests), not regular reads.
    """
    global _store
    with _lock:
        new_store = load_policies(policy_dir)
        _store = new_store
        logger.info(
            "Loaded %d polic%s from %s (%d error%s)",
            len(new_store),
            "y" if len(new_store) == 1 else "ies",
            policy_dir,
            len(new_store.errors),
            "" if len(new_store.errors) == 1 else "s",
        )
    return new_store
