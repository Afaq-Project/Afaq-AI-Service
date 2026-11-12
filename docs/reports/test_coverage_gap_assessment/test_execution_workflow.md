# Test Authoring and Codespaces Execution Workflow

## Goal

Close the coverage gaps in [the assessment](test_coverage_gap_report.md) for Specs 1 and 2, run the resulting deterministic and production-like checks in Codespaces, and produce a traceable issue report. The Codespaces workflow uses native PostgreSQL; it does not require Docker.

## End-to-end workflow

### 1. Establish the baseline

- Work from a dedicated feature branch containing the current implementation and the agreed test plan. Record the branch and commit SHA.
- Read the relevant requirements in `specs/001-security-validation-module/`, `specs/002-scraping-extraction-pipeline/`, API endpoint definitions, Pact contracts, existing tests, and the coverage gap assessment.
- Inventory current tests and scripts before adding coverage. Map each requirement/function to an existing or planned test ID; mark existing coverage as unit, mocked integration, real dependency integration, API, or k6.
- Confirm the Codespace runs the intended branch. Do not assume local uncommitted changes have been transferred.

### 2. Delegate test authoring

The primary agent must use multiple sub-agents for independent test-writing work. Follow the assignments and coordination rules in [the test implementation plan](test_implementation_plan.md). Give each agent its scope, source requirements, owned files, test boundary, and acceptance criteria. The primary agent owns shared fixtures, cross-suite interfaces, merge conflict resolution, and final traceability; agents must not independently edit shared fixtures without coordination.

### 3. Create and review environment scripts

- Create `scripts/codespaces_test_setup.sh` to provision/check native PostgreSQL, schema, Python dependencies, and real-browser prerequisites idempotently.
- Create `scripts/codespaces_test.sh` to run explicit test modes and, when requested, start/readiness-check/stop the API for HTTP and k6 runs.
- Keep credentials out of source and logs. Ensure scripts fail on setup/schema errors, preserve test exit codes, validate destructive database targets, and do not rely on Docker.
- Review both scripts for safe reruns, cleanup, branch/commit traceability, and no hidden external-network calls before running them.

### 4. Prepare the Codespace

- Push the feature branch only through the repository's normal review process; create/rebuild a Codespace from that branch so it contains the intended commit.
- Run the setup script and confirm PostgreSQL, Prisma schema/client, and Chromium readiness.
- Create a dedicated test database and seed minimal synthetic fixtures with a unique test API key. Give parallel integration runs isolated databases or namespaces.
- Start local fixture servers for crawler/browser and webhook behavior. Use an S3-compatible sandbox only where object-store semantics are specifically under test. Use stubbed or recorded LLM responses by default; a real model call is opt-in and must use a sandbox credential.

### 5. Write and review tests

- Start from behavior and requirements, not existing implementation details alone. Each test should state its observable precondition, action, and expected state/response.
- Cover positive, negative, boundary, retry, cancellation, concurrency, and recovery behavior where required by the spec.
- Keep ordinary tests deterministic and offline. Use real PostgreSQL/Chromium only in explicitly marked dependency integration suites; isolate their data and cleanup.
- Assert persisted state as well as HTTP responses for stateful workflows. For asynchronous operations, poll to terminal state with a bounded test harness and assert the final operation/source/listing/detail/DLQ state.
- Use meaningful unique identifiers and explicit fixture cleanup. Verify security failures do not cause writes or outbound side effects.
- Do not add arbitrary latency or total-runtime assertions. k6 is the only suite that evaluates load/performance, using the checked-in user-approved profile and controlled fixture sources.
- Validate each agent's suite independently, then run the combined relevant suites and inspect collection output to ensure tests were discovered.

### 6. Execute by risk tier

Use `scripts/codespaces_test.sh` (or equivalent documented commands) to run the following in sequence, preserving each command and result:

1. **Fast deterministic tests:** unit tests for URL/link validation, auth rules, file validation, language classification, pagination, prioritization, template matching/repair, state transitions, and error mapping.
2. **Contract/API tests:** Pact contract guard and HTTP tests for every documented endpoint, including authentication, validation failures, response envelopes, status codes, and stable field semantics.
3. **Native PostgreSQL integration:** actual Prisma client/schema with isolated database. Verify uniqueness, transactions, lock acquire/release/reclaim, same-key idempotency races, pagination ordering, retry/DLQ transitions, and cleanup after cancellation/failure.
4. **Real browser integration:** actual Chromium/Crawl4AI against local controlled pages. Verify JS-rendered content, redirects/SSRF boundaries, hidden tabs, pagination termination, multi-page caps, cancellation and browser cleanup.
5. **External-boundary integration:** S3-compatible storage, LLM, and webhook tests. Prefer service emulators/stubs; use only dedicated sandbox services for behavior not represented by a stub. Check success, timeout, malformed response, rejection, partial failure, retry, and no-side-effect behavior.
6. **Application HTTP smoke tests:** start the API against the test database, check health/readiness, then exercise valid and invalid authenticated requests with seeded data. Poll asynchronous scrape operations through completion and verify database state.
7. **k6 scenarios:** run the configured baseline and unexpected-burst profile against the isolated Codespace API and controlled source fixtures. Keep expected 4xx rejection checks separate from server-failure metrics; test same-key concurrent idempotency and distinct-key source-lock contention as separate cases. Capture thresholds, checks, request counts, and logs.
8. **Combined regression run:** rerun all relevant suites from the final candidate commit, then record the exact commit and results. Do not claim a tier passed if it was skipped or used a mock in place of the required real dependency.

Test runtime is not a release criterion for this expanded Codespaces exercise. Keep functional tests free of performance assertions; diagnose hangs with logs and process state rather than turning elapsed time into a behavior assertion.

### 7. Diagnose and track issues

For each failure, record:

- test ID, requirement/spec section, suite/tier, exact command, commit SHA, and sanitized logs;
- expected result versus actual HTTP response and persisted state;
- whether the failure is product behavior, test defect, environment/setup defect, or unavailable external dependency;
- reproduction steps and evidence, including whether the scenario was repeated from a clean database;
- severity, release impact, owner, and a regression test or follow-up task.

Do not weaken assertions or mark failures as expected merely to obtain a green run. Fix test defects separately from product defects; rerun the failing scenario, relevant suite, and final regression tiers. Distinguish `PASS`, `FAIL`, `BLOCKED` (dependency unavailable), and `NOT RUN` in the report.

### 8. Final report and handoff

Publish a concise report in the same assessment directory with coverage mapping, exact environment/commit, executed commands, passed/failed/blocked/not-run counts by tier, critical findings, non-blocking findings, and remaining gaps. Link each issue to evidence and a requirement. Include k6 configuration/profile and result artifacts without secrets. Stop the Codespace or ensure its idle timeout is set after the run.
