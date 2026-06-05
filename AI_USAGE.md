# AI Usage Policy

AI assistance is allowed in this repository for code, tests, and documentation.
All AI output is treated as draft material that requires human review.

## Core Rule

Maintainers are responsible for the final correctness, security, and behavior of all merged changes.

## Allowed Uses

- Generate or refactor implementation code.
- Generate or update tests.
- Draft documentation updates.
- Propose debugging strategies and edge-case handling.

## Required Validation Before Merge

- Review all edited files manually.
- Run relevant tests for changed modules.
- Verify no unintended regressions in GUI flows or API integrations.
- Confirm logging/error handling is appropriate.
- Keep dependency additions minimal and justified.

## Security-Sensitive Change Rules

For credential handling, network calls, filesystem writes, import/export, and backup/restore paths:

- Apply explicit manual review.
- Validate failure paths and recovery behavior.
- Ensure no secrets are committed to code, docs, or prompts.

Refer to SECURITY.md for vulnerability process details.

## Transparency

AI assistance should be disclosed in PR descriptions.

Suggested note:
- This change was developed with AI assistance and reviewed/tested by a maintainer.

Optional trailer:
- Co-authored-by: GitHub Copilot

## Disallowed

- Merging AI-generated changes without review.
- Including unverifiable or license-ambiguous generated code.
- Exposing private credentials or sensitive user data to AI tooling.

## Scope

This policy applies to code, tests, docs, and maintenance scripts in this repository.
