# Codespaces Test Environment Setup

## Purpose and scope

This guide defines a repeatable environment for running the expanded Spec 1 and Spec 2 tests in GitHub Codespaces. Run PostgreSQL as a native Linux service inside the Codespace. Docker and Docker Compose are not prerequisites for this workflow. The application and PostgreSQL share the Codespace VM; use isolated test data and credentials, never production services or credentials.

The repository currently has no Codespaces devcontainer configuration. The setup work therefore includes creating and reviewing the scripts below on a feature branch before rebuilding or creating a Codespace from that branch:

- `scripts/codespaces_test_setup.sh`: idempotently installs or verifies required system packages, starts PostgreSQL, creates a dedicated test role/database, applies the Prisma schema, and prepares Chromium/Crawl4AI prerequisites.
- `scripts/codespaces_test.sh`: validates required environment variables, runs selected test tiers, starts the API for live HTTP/k6 checks when requested, checks service readiness, captures logs and exit statuses, and cleans up processes it started.
- `.devcontainer/devcontainer.json` (optional): documents the Codespace base image/features and runs the setup script at an appropriate lifecycle hook. It must not assume Docker is available.

Do not put credentials or generated API keys in these scripts, Markdown, committed `.env` files, shell history, or test output. Read them from Codespaces secrets or an ignored local environment file. Check `.gitignore` before creating any environment file.

## Environment prerequisites

- A Codespace created from the feature branch containing the scripts and tests.
- Python 3.12 and `uv`, as required by `pyproject.toml`.
- Native PostgreSQL server/client packages and a running PostgreSQL service.
- Prisma CLI/client generated from the checked-in schema.
- Chromium and the browser dependencies required by the installed Crawl4AI version.
- k6 only for the HTTP/load-test phase; use the binary already provided by the environment when available.
- A dedicated database such as `afaq_codespaces_test`, with `DATABASE_URL` and `DIRECT_URL` both pointing to it. Use the Codespace-local PostgreSQL port unless the setup script deliberately configures another port.

The project settings read `DATABASE_URL`/`DIRECT_URL` for database access and support optional AI, S3-compatible storage, and webhook configuration. Keep external integrations disabled or replaced by deterministic test doubles in ordinary tests. Enable a real test service only with a dedicated sandbox resource and explicit test credentials.

## Setup script requirements

The primary agent should create `scripts/codespaces_test_setup.sh` with these properties:

1. Fail fast (`set -euo pipefail`), print actionable errors, and never print secret values.
2. Be safe to run repeatedly: detect installed packages, a running PostgreSQL service, existing role/database, and already-generated Prisma client before changing anything.
3. Install PostgreSQL and required OS/browser libraries through the Codespace's package manager when absent. Do not install or start Docker.
4. Start the native PostgreSQL service and wait for readiness using `pg_isready` (readiness polling is setup orchestration, not a test performance assertion).
5. Create a least-privilege test role and dedicated test database. Do not use a production role/database. Keep credentials out of the script; obtain them from environment variables or generate an ephemeral local-only password without echoing it.
6. Set `DATABASE_URL` and `DIRECT_URL` explicitly for the test database. Apply the checked-in Prisma schema using the repository's documented Prisma command, and fail if schema preparation fails. Do not suppress migration/schema errors.
7. Run `uv sync --all-groups` and generate the Prisma client with `uv run prisma generate`. Both commands must fail visibly if dependencies or client generation fail.
8. Install browser binaries/dependencies using the supported command for the locked Crawl4AI/Playwright version. Do not fetch unrelated tools or silently skip browser setup.
9. Run a readiness check for PostgreSQL, Python/uv, Prisma client, and Chromium. Report which checks passed.
10. Avoid destructive operations against databases not bearing the explicit test-only name. Any reset command must validate the target database name before dropping data.

If OS packages must be installed, use `sudo` only where required by the Codespace image and report a clear error if the environment does not permit it. Do not assume the default user is root.

The execution script should support explicit modes (for example `unit`, `integration`, `api`, `k6`, and `all`) rather than always starting every dependency. For API and k6 modes it should start Uvicorn against the test database, wait for `/health`, run the requested command, preserve its exit code, and stop only the process it started. Seed only isolated fixtures and clean them up when practical.

## Environment preparation sequence

From the repository root in the Codespace:

1. Confirm the checked-out branch and commit are the intended feature branch; a Codespace created from `main` will not contain unpushed local changes.
2. Configure test-only secrets/environment values through Codespaces secrets or an ignored environment file. At minimum, set database URLs and a test API key. Add Google/Anthropic, S3, or webhook credentials only for a separately approved sandbox test that needs the real integration.
3. Run `bash scripts/codespaces_test_setup.sh` and inspect its summary. Stop on any failed readiness or schema check.
4. Run the API-key/database fixture seed step with an ephemeral key. Never reuse the fixed sample key in `scripts/seed_test_db.py` for a shared or production-like environment; review that script before use and replace its static credential behavior as part of test hardening.
5. Confirm the seeded key is accepted and an invalid key is rejected. Confirm the database contains only test fixtures.
6. Run tests in the order and scopes in [the workflow](test_execution_workflow.md). Keep a run log with commit SHA, environment mode, database/schema version, commands, results, and issue references; redact secrets and sensitive scraped content.

## Data and cleanup rules

- Use synthetic source records and controlled fixture websites. Do not crawl real third-party sites during automated integration tests.
- Do not point tests at production databases, buckets, model accounts, or webhook consumers.
- Give each parallel worker its own test database/schema or unique fixture namespace. Do not allow concurrent agents to reset a shared database.
- Keep fixtures deterministic and avoid assertions on wall-clock performance. The expanded Codespaces validation has no overall execution-time budget; performance/latency assertions belong only in user-configured k6 tests.
- Preserve useful logs and sanitized failure artifacts. Remove test rows, temporary objects, and background processes after each run.

## References

- [GitHub Codespaces deep dive](https://docs.github.com/en/codespaces/about-codespaces/deep-dive)
- [GitHub Codespaces: setting up a project](https://docs.github.com/en/codespaces/setting-up-your-project-for-codespaces)
- Project environment configuration: `src/modules/core/config/settings.py`, `prisma/schema.prisma`, `pyproject.toml`, and `specs/002-scraping-extraction-pipeline/quickstart.md`.
