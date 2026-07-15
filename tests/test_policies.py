"""Tests for the Markdown policy loading, caching, and reload engine."""

from __future__ import annotations

from pathlib import Path

from app import policies


def test_slugify_normalises_arbitrary_text() -> None:
    assert policies.slugify("  Code of Conduct! ") == "code-of-conduct"
    assert policies.slugify("6.2 Voting & Conflicts") == "6-2-voting-conflicts"


def test_load_policies_extracts_title_and_sections(tmp_path: Path) -> None:
    (tmp_path / "disciplinary.md").write_text(
        "# Disciplinary Policy\n\n## Section 3: Process\n\n### 3.4 Sanctions\n\nBody text.\n",
        encoding="utf-8",
    )

    store = policies.load_policies(tmp_path)

    assert len(store) == 1
    assert store.errors == ()
    policy = store.get("disciplinary")
    assert policy is not None
    assert policy.title == "Disciplinary Policy"
    assert "<h2" in policy.html
    headings = [section.heading for section in policy.sections]
    assert "Section 3: Process" in headings
    assert "3.4 Sanctions" in headings


def test_load_policies_falls_back_to_filename_when_no_heading(tmp_path: Path) -> None:
    (tmp_path / "racing_policy.md").write_text(
        "Some body text with no heading.\n", encoding="utf-8"
    )

    store = policies.load_policies(tmp_path)

    policy = store.get("racing-policy")
    assert policy is not None
    assert policy.title == "Racing Policy"


def test_load_policies_excludes_readme(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Not a policy\n", encoding="utf-8")
    (tmp_path / "constitution.md").write_text("# Constitution\n", encoding="utf-8")

    store = policies.load_policies(tmp_path)

    assert len(store) == 1
    assert store.get("constitution") is not None
    assert store.get("readme") is None


def test_load_policies_skips_malformed_file_without_crashing(tmp_path: Path) -> None:
    good = tmp_path / "constitution.md"
    good.write_text("# Constitution\n", encoding="utf-8")
    bad = tmp_path / "corrupt.md"
    bad.write_bytes(b"\xff\xfe\x00invalid utf-8")

    store = policies.load_policies(tmp_path)

    assert len(store) == 1
    assert store.get("constitution") is not None
    assert len(store.errors) == 1
    assert store.errors[0].filename == "corrupt.md"


def test_load_policies_reports_duplicate_slugs(tmp_path: Path) -> None:
    (tmp_path / "race-conduct.md").write_text("# Race Conduct A\n", encoding="utf-8")
    (tmp_path / "race_conduct.md").write_text("# Race Conduct B\n", encoding="utf-8")

    store = policies.load_policies(tmp_path)

    assert len(store) == 1
    assert len(store.errors) == 1
    assert "duplicate slug" in store.errors[0].error


def test_load_policies_missing_directory_reports_error(tmp_path: Path) -> None:
    store = policies.load_policies(tmp_path / "does-not-exist")

    assert len(store) == 0
    assert len(store.errors) == 1


def test_reload_store_picks_up_added_and_removed_files(tmp_path: Path) -> None:
    (tmp_path / "constitution.md").write_text("# Constitution\n", encoding="utf-8")
    store = policies.reload_store(tmp_path)
    assert store.get("constitution") is not None
    assert policies.get_store().get("constitution") is not None

    (tmp_path / "membership.md").write_text("# Membership\n", encoding="utf-8")
    (tmp_path / "constitution.md").unlink()

    store = policies.reload_store(tmp_path)
    assert store.get("constitution") is None
    assert store.get("membership") is not None
    assert policies.get_store().get("constitution") is None
