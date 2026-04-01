# AGENTS.md

Purpose: machine-readable and auditor-friendly guidance for AI agents that modify this repository.

This file complements README.md (human-facing) and AI_USAGE.md (policy-facing).

## Repository Scope

Applies to all files in this repository unless a deeper AGENTS.md overrides these rules for a subdirectory.

## Core Operating Rules

- Treat AI output as draft material; maintainers are accountable for final changes.
- Prefer minimal, focused edits over broad refactors.
- Preserve project style and existing architecture unless explicitly asked to change it.
- Do not add secrets, tokens, credentials, or personal data to code, docs, prompts, or commit messages.
- Avoid introducing dependencies unless they are necessary and justified.

## Safety-Critical Areas

When changing credentials, network behavior, filesystem writes, import/export, backup/restore, or authentication-related code:

- Apply extra manual review.
- Keep secure defaults and least-privilege behavior.
- Validate error handling and failure paths.
- Cross-check against SECURITY.md.

## Documentation Expectations

For behavior changes, update relevant docs in the same change set when practical:

- README.md for user-facing behavior
- AI_USAGE.md for AI workflow policy
- SECURITY.md for reporting/security process updates
- AGENTS.md for machine workflow contract changes

## Testing Expectations

Before proposing merge-ready changes:

- Run relevant tests for affected modules when feasible.
- Add or update tests for new behavior or bug fixes.
- If tests cannot be run, clearly state what was not validated.

## Commit and PR Transparency

AI-assisted changes should be disclosed in PR descriptions.

Recommended PR note:
- This change was developed with AI assistance and reviewed/tested by a maintainer.

Optional commit trailer:
- Co-authored-by: GitHub Copilot

## Non-Goals for Agents

- Do not claim unverified results.
- Do not fabricate links, test outcomes, or runtime behavior.
- Do not silently ignore conflicting repository instructions.

## Quick Audit Checklist

- Scope of change is minimal and intentional.
- No secrets or sensitive data introduced.
- Security-sensitive edits received explicit scrutiny.
- Docs updated where needed.
- Relevant tests updated/run or explicitly deferred.
