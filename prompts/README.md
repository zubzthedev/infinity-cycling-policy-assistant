# Prompts

Holds the prompt framework assembled on every request (see `app/prompts.py`,
added in Milestone 4):

- `system.md` — defines Ask Oufy's identity, scope, and behaviour rules.
- `response_rules.md` — the required response structure (Applicable Policies,
  Summary, Reasoning, Recommended Process, Policy References).
- `examples.md` — few-shot examples demonstrating the expected output format.

These are loaded once at startup, cached, and reloadable by an administrator
without restarting the application — the same pattern used for `policies/`.
