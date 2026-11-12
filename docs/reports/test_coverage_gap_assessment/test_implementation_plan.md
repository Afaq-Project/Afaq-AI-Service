# Test Implementation Plan for Specs 1 and 2

## Objective

Implement the coverage additions in [the test coverage gap assessment](test_coverage_gap_report.md), prepare repeatable Codespaces execution using native PostgreSQL, and verify outcomes through controlled test dependencies. This is a test and environment plan; it does not authorize changes to production behavior or quality gates merely to make tests pass.

## Primary-agent responsibilities

The primary agent coordinates the work and remains accountable for the final suite. The primary agent must delegate independent test-writing work to at least four sub-agents so suites can be developed in parallel. Each sub-agent receives one bounded assignment below and owns its test files. The primary agent owns shared fixture APIs, shared setup scripts, Codespaces execution, cross-suite consistency, review, integration, and final requirement-to-test traceability.

Before delegation, the primary agent must:

1. Create/confirm a feature branch and capture the starting commit.
2. Freeze test interfaces and shared fixtures (fixture server API, database isolation strategy, test IDs, naming conventions) in a short coordination note.
3. Assign separate files/directories to agents. Avoid two agents editing `conftest.py`, database bootstrap, global settings, or the same test module at once.
4. Require each agent to identify the source requirement, scenario, assertions, external boundaries, cleanup, and commands used for its work.
5. Review each agent's tests for meaningful behavior assertions, realistic states, determinism, no production credentials, and no accidental external traffic.

## Parallel sub-agent assignments

| Agent | Test area and ownership | Required scenarios / acceptance |
|---|---|---|
| **Agent 1: PostgreSQL and repository consistency** | Add tests under a dedicated `tests/integration/postgres/` area for actual Prisma/PostgreSQL behavior. Do not modify shared setup scripts; propose fixture changes to the primary agent. | Apply the checked-in schema to an isolated Codespaces PostgreSQL database. Verify concurrent same-key idempotency, competing source locks, unique listing/detail writes, stale-lock reclamation, transaction rollback, operation ordering/pagination, and consistency after cancellation/failure. Assert database rows, not only repository return values. Provide cleanup and a command to run only this suite. |
| **Agent 2: Browser and crawl workflow** | Add real Chromium/Crawl4AI integration tests in a dedicated `tests/integration/browser/` area; use a local controlled fixture server. | Exercise JS-rendered pages, redirects, pagination variants, repeated/stagnant pages, known-listing cutoff, hidden tabs, multi-page depth cap, challenge/429 handling, DNS/SSRF protections at the browser boundary where safely reproducible, cancellation during navigation, and browser/context cleanup. No real third-party crawling. |
| **Agent 3: Onboarding, templates, and AI boundary** | Add tests in a separate Stage 0/template integration test module. Keep shared LLM fixtures under an agent-owned fixture file or request primary-agent review before shared changes. | Verify valid controlled portal onboarding and saved config; irrelevant portal rejection without writes; prompt injection/untrusted page text isolation; robots/preflight/reachability branches; persisted template reuse without schema-generation calls; soft-drift repair, invalid repair rejection, and preservation of the previous valid template. Use deterministic fake/recorded LLM responses by default; real sandbox LLM tests remain opt-in. |
| **Agent 4: S3, retries, DLQ, webhook, and failure cleanup** | Add tests in a distinct storage/reliability module under `tests/integration/`. Coordinate the storage test boundary with the primary agent. | Verify valid document bytes/checksum/metadata, cache reuse, over-limit and invalid magic/archive rejection before upload, interrupted stream/upload cleanup, transient retries then success, exhaustion to DLQ with error history, no retry of permanent failures, webhook success/failure/retry semantics, and lock/resource cleanup after dependency errors. Use local fakes/emulators unless the behavior requires an isolated S3 sandbox. |

The primary agent may assign a fifth agent to API/Pact/k6 scenario authoring if these do not conflict with existing owners. That assignment should cover every registered Spec 2 route, response schema and status behavior, full operation polling, seeded pagination/order, concurrent same-key idempotency, distinct-key lock contention, and k6 assertions that fail on malformed/missing response data. Do not use Pact as the only source of test requirements; trace to specs and implementation as well.

## Primary-agent implementation sequence

### Phase A: Test environment and shared harness

1. Create `scripts/codespaces_test_setup.sh` and `scripts/codespaces_test.sh` following [the environment setup guide](codespaces_environment_setup.md).
2. Prepare native PostgreSQL with a dedicated test database, Prisma schema/client, Python dependencies, and Chromium. No Docker dependency.
3. Define isolated database and fixture-server conventions for agents. Ensure each concurrent DB integration run uses a distinct database/schema or serialized access.
4. Establish ephemeral test API-key seeding. Review and replace static credential assumptions in `scripts/seed_test_db.py` before using it for shared Codespaces execution.

### Phase B: Parallel authoring and integration

1. Launch Agents 1–4 with bounded file ownership and acceptance criteria above.
2. While they work, the primary agent fills route/API coverage gaps and prepares the master traceability matrix from Spec 1, Spec 2, endpoint docs, and Pact interactions.
3. Review returned tests independently; reject tests that only assert mocks were called when the requirement is an observable state or response.
4. Integrate suites without shared-fixture collisions. Keep real dependency integration tests clearly marked and separately selectable from deterministic unit tests.

### Phase C: Layered Codespaces execution

Follow [the test execution workflow](test_execution_workflow.md): unit tests, Pact/API tests, real PostgreSQL integration, real browser integration, storage/LLM/webhook boundary tests, live local API smoke tests, then k6 baseline and unexpected-burst profiles. Capture exact commands, commit, settings, sanitized logs, and tier outcomes. No overall Codespaces run-time limit is imposed for this expanded validation; do not add execution-time expectations to functional tests.

### Phase D: Findings and completion criteria

The plan is complete only when:

- every applicable Spec 1/Spec 2 requirement and API endpoint maps to a maintained test or a clearly justified `NOT TESTED` item;
- critical workflows have at least one test across the real dependency boundary where the gap report requires it;
- same-key idempotency and competing source-lock behavior are exercised concurrently against PostgreSQL;
- browser, DB, storage, and worker cleanup/recovery have assertions;
- all commands and outcomes are reported as `PASS`, `FAIL`, `BLOCKED`, or `NOT RUN`, with no skipped tier described as passed;
- each remaining issue has a severity, evidence, reproduction, owner/follow-up, and release impact;
- the final report and sanitized artifacts are stored beside the coverage gap assessment.

## Rules for all agents

- Use English and follow `AGENT.md`, applicable architecture rules, specs, and API contracts.
- Keep unit tests offline and deterministic. Use isolated fixtures for integration tests; no production network, credentials, database, bucket, or webhook.
- Do not weaken code, contracts, security policies, architecture rules, or quality gates to satisfy an assertion.
- Do not duplicate well-covered behavior without a distinct cross-component invariant.
- Assert externally observable behavior and persisted state. Include failure and cleanup assertions for stateful workflows.
- Use synthetic sites and seeded test data. Redact keys, URLs with credentials, personal information, and scraped content from logs.
- Do not make functional tests assert latency or total suite duration. Use k6 for performance/load observations under the approved configuration.
- Do not run destructive database resets unless the target is explicitly validated as the isolated test database.
- Report the exact files changed, requirements covered, commands run, results, and known gaps when returning work to the primary agent.
