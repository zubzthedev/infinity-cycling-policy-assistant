"""Assembles the prompt framework sent to Gemini on every request.

Prompt fragments (system instructions, response rules, few-shot examples)
are stored as separate Markdown files under `prompts/`, loaded once at
startup and cached in memory - the same load-once pattern used for
policies. Every request concatenates, in a fixed order: system prompt,
response rules, examples, every policy document, then the user's question.
There is no retrieval step - the policy library is small enough to fit
comfortably in Gemini's context window, so every document is always
included in full.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from app.policies import PolicyStore

logger = logging.getLogger("ask_oufy.app")

_REQUIRED_FILES = ("system.md", "response_rules.md", "examples.md")


@dataclass(frozen=True)
class PromptSet:
    """The three prompt fragments that make up Ask Oufy's prompt framework."""

    system: str
    response_rules: str
    examples: str


_EMPTY_PROMPT_SET = PromptSet(system="", response_rules="", examples="")

_lock = threading.Lock()
_prompts: PromptSet = _EMPTY_PROMPT_SET


def load_prompts(prompt_dir: Path) -> PromptSet:
    """Load the three required prompt fragment files from disk.

    Unlike policies, a missing or unreadable prompt file is a configuration
    error rather than a normal operating condition - Ask Oufy cannot safely
    answer questions without its system prompt and response rules, so this
    raises rather than silently degrading.
    """
    values: dict[str, str] = {}
    for filename in _REQUIRED_FILES:
        path = prompt_dir / filename
        try:
            values[filename] = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"Failed to load required prompt file {path}: {exc}") from exc

    return PromptSet(
        system=values["system.md"],
        response_rules=values["response_rules.md"],
        examples=values["examples.md"],
    )


def get_prompts() -> PromptSet:
    """Return the currently loaded prompt set (no I/O)."""
    return _prompts


def reload_prompts(prompt_dir: Path) -> PromptSet:
    """Reload the prompt fragments from disk and atomically swap them in."""
    global _prompts
    with _lock:
        new_prompts = load_prompts(prompt_dir)
        _prompts = new_prompts
        logger.info("Loaded prompt framework from %s", prompt_dir)
    return new_prompts


def estimate_tokens(text: str) -> int:
    """A rough, fast token-count estimate (~4 characters per token)."""
    return max(1, len(text) // 4)


def build_prompt(question: str, store: PolicyStore, prompts: PromptSet) -> str:
    """Assemble the full prompt sent to Gemini, in the required fixed order.

    Order: system prompt, response rules, examples, every policy document
    (each clearly delimited so the model - and our own reference-matching
    logic in a later milestone - can tell documents apart), then the
    user's question.
    """
    parts: list[str] = [prompts.system, prompts.response_rules, prompts.examples]

    for policy in store:
        parts.append(
            f"### POLICY DOCUMENT: {policy.title} ({policy.filename})\n\n{policy.raw_markdown}"
        )

    parts.append(f"### USER QUESTION\n\n{question}")

    prompt = "\n\n---\n\n".join(part for part in parts if part)
    logger.info("Built prompt (~%d tokens estimated)", estimate_tokens(prompt))
    return prompt
