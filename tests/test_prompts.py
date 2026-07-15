"""Tests for the prompt framework: loading, reload, and assembly ordering."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import policies, prompts


def _write_prompt_files(directory: Path, *, system: str = "SYSTEM", rules: str = "RULES",
                         examples: str = "EXAMPLES") -> None:
    (directory / "system.md").write_text(system, encoding="utf-8")
    (directory / "response_rules.md").write_text(rules, encoding="utf-8")
    (directory / "examples.md").write_text(examples, encoding="utf-8")


def test_load_prompts_reads_all_three_files(tmp_path: Path) -> None:
    _write_prompt_files(tmp_path, system="Be Ask Oufy.", rules="Use headings.", examples="Q&A.")

    prompt_set = prompts.load_prompts(tmp_path)

    assert prompt_set.system == "Be Ask Oufy."
    assert prompt_set.response_rules == "Use headings."
    assert prompt_set.examples == "Q&A."


def test_load_prompts_raises_on_missing_file(tmp_path: Path) -> None:
    (tmp_path / "system.md").write_text("SYSTEM", encoding="utf-8")
    (tmp_path / "response_rules.md").write_text("RULES", encoding="utf-8")
    # examples.md intentionally missing

    with pytest.raises(RuntimeError, match="examples.md"):
        prompts.load_prompts(tmp_path)


def test_reload_prompts_updates_cache(tmp_path: Path) -> None:
    _write_prompt_files(tmp_path, system="Version 1")
    prompts.reload_prompts(tmp_path)
    assert prompts.get_prompts().system == "Version 1"

    _write_prompt_files(tmp_path, system="Version 2")
    prompts.reload_prompts(tmp_path)
    assert prompts.get_prompts().system == "Version 2"


def test_estimate_tokens_is_roughly_proportional_to_length() -> None:
    short = prompts.estimate_tokens("abcd")
    long = prompts.estimate_tokens("abcd" * 100)

    assert short == 1
    assert long == 100


def test_build_prompt_assembles_sections_in_required_order(tmp_path: Path) -> None:
    policy_dir = tmp_path / "policies"
    policy_dir.mkdir()
    (policy_dir / "constitution.md").write_text(
        "# Constitution\n\nConflict of interest rules.\n", encoding="utf-8"
    )
    (policy_dir / "disciplinary.md").write_text(
        "# Disciplinary Policy\n\nSanctions process.\n", encoding="utf-8"
    )
    store = policies.load_policies(policy_dir)

    prompt_set = prompts.PromptSet(
        system="SYSTEM_MARKER", response_rules="RULES_MARKER", examples="EXAMPLES_MARKER"
    )
    question = "Can a member be suspended?"

    prompt = prompts.build_prompt(question, store, prompt_set)

    # Every expected section is present...
    for marker in (
        "SYSTEM_MARKER",
        "RULES_MARKER",
        "EXAMPLES_MARKER",
        "Conflict of interest rules.",
        "Sanctions process.",
        question,
    ):
        assert marker in prompt

    # ...and appears in the mandated order.
    positions = [
        prompt.index(marker)
        for marker in (
            "SYSTEM_MARKER",
            "RULES_MARKER",
            "EXAMPLES_MARKER",
            "Conflict of interest rules.",
            "Sanctions process.",
            question,
        )
    ]
    assert positions == sorted(positions)


def test_build_prompt_includes_policy_document_headers(tmp_path: Path) -> None:
    policy_dir = tmp_path / "policies"
    policy_dir.mkdir()
    (policy_dir / "racing.md").write_text("# Racing Policy\n\nMarshal duties.\n", encoding="utf-8")
    store = policies.load_policies(policy_dir)
    prompt_set = prompts.PromptSet(system="S", response_rules="R", examples="E")

    prompt = prompts.build_prompt("Which policy governs marshal duties?", store, prompt_set)

    assert "POLICY DOCUMENT: Racing Policy (racing.md)" in prompt
