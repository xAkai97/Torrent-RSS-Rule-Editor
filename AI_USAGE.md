# AI Usage Policy

This project allows AI-assisted coding as a productivity aid, with strict human accountability.

## Guiding Principle

AI output is a draft, not an authority. Maintainers are responsible for all merged changes.

## Allowed Uses

- Drafting and refactoring code
- Generating or improving tests
- Improving documentation and comments
- Suggesting bug fixes and edge-case handling

## Required Review Standards

Before merging AI-assisted changes:

- Read and understand all modified code paths
- Confirm behavior with relevant tests
- Check for regressions in UI and data flow
- Verify error handling and logging quality
- Ensure dependency changes are intentional and minimal

## Security Requirements

For security-relevant areas (credentials, network calls, filesystem writes, import/export, backup/restore):

- Perform explicit manual review
- Prefer least-privilege and safe defaults
- Confirm no secrets are introduced in code, commits, or prompts
- Validate failure paths, not only happy paths

See [SECURITY.md](SECURITY.md) for vulnerability reporting and disclosure expectations.

## Attribution and Transparency

Attribution of AI assistance in PR descriptions is encouraged.

Suggested PR note:
- "This change was developed with AI assistance and fully reviewed/tested by a maintainer."

Optional commit trailer format:
- "Co-authored-by: GitHub Copilot"

## Disallowed Practices

- Blindly merging AI-generated code without review
- Using AI output that introduces unverifiable external code or licensing ambiguity
- Sharing private credentials, tokens, or sensitive user data with AI tools

## Scope

This policy applies to source code, tests, docs, and maintenance scripts in this repository.
