# k6 Test Definition: Scraping and Extraction Pipeline

This document defines the k6 test coverage and exact scenarios for Spec 2. Use it with [load_test_configuration.md](load_test_configuration.md), which supplies VUs, durations, limits, and environment variables. Translate these definitions into executable k6 tests; do not infer performance SLOs where this document marks them TBD.

## Scope and execution rules

- Exercise the deployed API through HTTP and assert externally observable behavior. k6 does not inspect PostgreSQL or internal Python objects; use operation responses, webhook capture, and test-environment data/setup to verify outcomes.
- Use dedicated, pre-onboarded test sources and test-only target websites/documents. Do not scrape arbitrary public sites as load-test data.
- `K6_BASE_URL`, `K6_API_KEY`, `K6_SOURCE_IDS`, `K6_LOCKED_SOURCE_ID`, `K6_INACTIVE_SOURCE_ID`, and `K6_KNOWN_OPERATION_ID` are required. The runner must fail closed when they are absent or malformed; do not supply production-like defaults.
- Valid/irrelevant onboarding scenarios require operator-supplied controlled fixtures via `K6_TEST_VALID_PORTAL_URL` and `K6_TEST_IRRELEVANT_PORTAL_URL`, with `K6_ENABLE_ONBOARDING=true`. Without those fixtures, mark ONB-01/ONB-02 blocked and run only the SSRF/malformed-input cases.
- Every request to a scraping control endpoint must include `X-API-Key: ${K6_API_KEY}` unless the scenario intentionally tests missing or invalid authentication.
- Run tests against `K6_BASE_URL` in a non-production environment. Honor the `baseline` and `unexpected_burst` limits in the companion configuration.
- Each scenario has a unique ID prefix for test data. Reuse an idempotency key only when deliberately repeating the same logical trigger; use new keys for independent operations.
- Trigger endpoints are asynchronous: assert acknowledgement and operation tracking, then poll status rather than treating the initial response as job completion.

## Postponed scenarios

**ONB-01 and ONB-02 were postponed in the Codespaces run on 2026-11-15.** They were not failures: no controlled onboarding portal fixtures were configured. The k6 implementation logs these scenarios as `BLOCKED` and runs ONB-03's SSRF and malformed-URL checks instead. See the [postponed-scenario record](../../docs/reports/scraping_extraction_pipeline/k6_postponed_scenarios.md) for fixture requirements and how to run them.

## Endpoint coverage

| ID | Endpoint | Required scenarios | Expected result |
| --- | --- | --- | --- |
| API-01 | `POST /api/v1/scrape/sources/onboard` | ONB-01 valid portal; ONB-02 irrelevant portal; ONB-03 SSRF/invalid URL; AUTH-01 missing/invalid key | Valid portal returns `200` with source/config data; irrelevant portal returns `400`; unsafe/malformed URL returns `422`; missing/invalid key returns `401`. |
| API-02 | `POST /api/v1/scrape/run` | RUN-01 one source; RUN-02 omitted `source_ids` (all active sources); RUN-03 same idempotency key repeated; RUN-04 malformed UUID; RUN-05 all requested sources locked; RUN-06 unexpected concurrent triggers; AUTH-01 | New operation returns `202` and an `operation_id`; duplicate key in 15 minutes returns `200` with the same ID and creates no duplicate operation; malformed IDs return `422`; all locked sources return `409`; unauthorized requests return `401`. |
| API-03 | `GET /api/v1/scrape/operations` | OPS-01 paginated list; OPS-02 status filter; OPS-03 empty/out-of-range page; AUTH-01 | `200`; pagination and optional status filter are reflected in returned data; empty results are valid. |
| API-04 | `GET /api/v1/scrape/operations/latest` | OPS-04 no operations; OPS-05 active operation; OPS-06 most recent terminal operation | `200`; returns `data: null` when empty, active operation while one runs, otherwise the latest operation. |
| API-05 | `GET /api/v1/scrape/operations/{operation_id}` | OPS-07 running and terminal operation; OPS-08 unknown ID; AUTH-01 | `200` with matching ID/status/telemetry; unknown operation returns `404`; unauthorized returns `401`. |
| API-06 | `POST /api/v1/scrape/operations/{operation_id}/abort` | ABT-01 abort a running operation; ABT-02 abort terminal operation; ABT-03 unknown ID | Running operation returns `200`, becomes `aborted`, and releases acquired source locks; terminal operation returns `400`; unknown ID returns `404`. |
| API-07 | `POST /api/v1/scrape/sources/{source_id}/abort` | ABT-04 halt active source in a multi-source batch; ABT-05 inactive/unlocked source; ABT-06 unknown source | Active source returns `200` and is unlocked/aborted; remaining sources continue; inactive source returns `400`; unknown source returns `404`. |
| API-08 | `GET /api/v1/scrape/dead-letter` | DLQ-01 list listing failures; DLQ-02 list detail failures; DLQ-03 pagination and empty queue; AUTH-01 | `200` with selected entity type, pagination, retry count, permanent-failure status, and error history. |

`AUTH-01`: send each applicable endpoint one request with no API key and one with an invalid API key; both must return `401`.

## Precise test scenarios

### ONB-01 — Onboard a valid educational portal

1. Submit `POST /api/v1/scrape/sources/onboard` with `K6_TEST_VALID_PORTAL_URL` and a unique test name.
2. Assert `200`, `status == "success"`, non-empty `source_id` and domain, `is_active == true`, and populated pagination/rate-limit configuration.
3. Submit again for the same URL if the fixture supports existing-source onboarding; assert the documented update/reuse behavior without creating duplicate active sources. If the API contract does not define repeat behavior, record it without a pass/fail assertion.

### ONB-02 — Reject a reachable but irrelevant portal

1. Submit onboarding for `K6_TEST_IRRELEVANT_PORTAL_URL`, a controlled reachable commercial/non-educational fixture.
2. Assert `400` and the `ERR_NOT_OPPORTUNITY_PORTAL` classification; verify no active onboarded source is reported.

### ONB-03 — Reject unsafe or malformed onboarding URLs

1. Submit a syntactically valid URL resolving to a test private/link-local target, then a malformed URL.
2. Assert `422` for security rejection or invalid URL according to the endpoint contract; ensure the response does not disclose credentials or internal network data.

### RUN-01 — Trigger, track, and complete a single-source scrape

1. Use a pre-onboarded deterministic portal fixture with `K6_SOURCE_IDS` containing its UUID and a fresh idempotency UUID.
2. Submit `POST /api/v1/scrape/run`; assert `202`, accepted status, valid `operation_id`, and correct queued count.
3. Poll `GET /api/v1/scrape/operations/{operation_id}` at the configured interval until terminal status, bounded by the configured 20-minute operation ceiling.
4. Assert the operation completes (or reports the fixture's explicitly configured partial/failure outcome), counts are non-negative and internally consistent, and `completed_at` is set for terminal status.
5. Assert `GET /api/v1/scrape/operations/latest` identifies the active operation during execution when observable and returns the latest operation after completion.

### RUN-02 — Trigger without source IDs

1. In a dedicated test database containing only active test sources, enable `K6_ENABLE_OMITTED_SOURCE_IDS=true` and submit a valid trigger body omitting `source_ids` with a fresh idempotency key. The default suite leaves this opt-in disabled to avoid scheduling unrelated active sources.
2. Assert `202` and that the returned queued/attempted sources correspond only to active, eligible test-environment sources.
3. Poll operation status to terminal state. Do not use this scenario in a shared environment containing non-test active sources.

### RUN-03 — Idempotency under retry and burst

1. Submit one trigger for a test source with idempotency key `K`.
2. Concurrently submit 5 identical logical trigger requests using the same valid UUID key `K` within 15 minutes. Use an HTTP batch to inspect all responses in one k6 VU.
3. Assert one unique `operation_id` across all successful responses; initial request may be `202`, deduplicated requests must be `200`; verify the operations log has exactly one operation associated with this key if the API exposes enough data, otherwise verify no more than one execution starts via operation telemetry/webhook capture.

### RUN-04/05/06 — Trigger validation, locks, and concurrent distinct jobs

1. **Malformed ID:** submit an invalid source UUID; assert `422`.
2. **Locked source:** while a fixture operation holds the source lock, trigger that source; assert `409` when all requested sources are locked, or a successful operation with the source recorded as skipped when mixed with eligible sources.
3. **Distinct concurrent triggers:** concurrently submit up to 5 independent trigger requests with distinct idempotency keys and overlapping source IDs. Assert no source is crawled by two operations at once, conflicts/skips are represented by the documented response/telemetry, and service remains responsive. Do not assert a specific scheduling order unless the fixture's priority values make it deterministic.

### OPS-01 through OPS-08 — Operation queries

1. Seed at least 3 test operations with distinguishable timestamps/statuses using normal API-driven fixture work.
2. Request `GET /operations?limit=2&offset=0`, then `offset=2`; assert page size, non-overlap, and reverse chronological order.
3. Request a supported `status` filter; assert every returned record matches it.
4. Query latest while one operation is running, then after it completes; assert active/latest selection rules.
5. Fetch a known operation and a well-formed unknown UUID; assert `200` and `404` respectively.
6. Query an offset beyond the record count; assert `200` with an empty list and valid total count.

### ABT-01 — Abort an active operation

1. Trigger a deliberately long-running test fixture operation (controlled delay must be in the fixture, not a sleep added to k6).
2. Confirm status is `running`, then submit the abort endpoint.
3. Assert `200`, status `aborted`, abort timestamp, and released-lock count.
4. Poll operation and source state through available APIs; assert no further work is attributed to the aborted operation and the source can be triggered again.

### ABT-02/03 — Abort terminal or nonexistent operation

1. Abort an already completed test operation; assert `400`.
2. Abort an unknown UUID; assert `404`.

### ABT-04 — Selectively halt one source in a batch

1. Trigger a multi-source operation with at least two controlled sources; wait until the first selected source is active.
2. Abort that source using `POST /sources/{source_id}/abort`.
3. Assert `200`, source status is aborted/unlocked, the batch continues with the other source, and the final operation reports partial-abort/remaining source outcome.

### ABT-05/06 — Halt inactive or unknown source

1. Abort a known unlocked source; assert `400`.
2. Abort an unknown UUID; assert `404`.

### PIPE-01 — Catalog discovery, pagination, and termination

1. Run against a deterministic fixture with query, path, or next-button pagination and known catalog pages.
2. Assert operation telemetry records the expected discovered listing count and completes catalog collection before detail extraction outcomes appear.
3. Use separate fixtures for zero-card page, disabled/absent next control, circular page fingerprint, stagnant page fingerprint, and HTTP 404/410; assert traversal terminates and does not exceed configured `max_pages_per_run`.
4. For chronological fixtures, make two consecutive pages contain only known listings; assert early cutoff after the second all-known page.

### PIPE-02 — Detail extraction, tabs, and multi-page article cap

1. Scrape a fixture with a detail page containing hidden tab panels and known fields; assert detail extraction count and expected field-presence through the test fixture's observable output/telemetry.
2. Scrape a multi-page article fixture with 6 pages; assert only the first 5 pages are traversed, lineage/depth is bounded to 4, and the cap is reflected in logs/telemetry where exposed.

### PIPE-03 — Stage 0 discovery security and relevance

1. Run valid onboarding with `robots.txt` delay/sitemap and homepage-to-catalog second hop; assert discovered config is persisted in API response and used by the scrape operation.
2. Run commercial/parking and challenge fixtures; assert typed rejection/cooldown behavior, no successful onboarding, and no duplicate operation for the rejected source.
3. The prompt-injection boundary, DOM skeleton token size, and absence of unintended LLM calls are internal behaviors; verify through test instrumentation or telemetry where available, not timing assertions.

### PIPE-04 — Template reuse, drift repair, and validation

1. Run the same known layout twice; assert the second run succeeds using the existing template and template-hit telemetry increases without schema regeneration.
2. Run a soft-drift fixture where one optional field selector changes; assert repair creates a new minor template version and the repaired field is populated on a subsequent run.
3. Run invalid-schema/hard-drift fixtures; assert invalid selectors/schemas are rejected and the operation records a controlled failure rather than persisting an invalid template.

### PIPE-05 — Language pairing and document ingestion

1. Scrape paired Arabic and English pages for the same opportunity; assert both details are present and share the same `opportunity_group_id` via supported operation output or test-environment readback.
2. Provide valid PDF/DOCX fixtures under the 25 MB limit; assert successful ingestion telemetry, checksum/S3 metadata, and subsequent URL cache reuse (no second upload, verified by fixture S3 counters/readback).
3. Provide invalid magic-byte and archive-bomb fixtures; assert rejection and no S3 object upload.

### PIPE-06 — Dead-letter queue and retry transitions

1. Use a listing fixture configured to fail extraction; trigger retries until `retry_count == 3`.
2. Assert the record becomes `failed_permanently`, includes error history, and is returned by `GET /dead-letter?entity_type=listings`.
3. Repeat for detail entity; assert `entity_type=details` returns the matching record and pagination works.

### PIPE-07 — Timeout, stale locks, and webhook delivery

1. **Operation ceiling:** use a controlled slow fixture and assert the run ends as `timed_out` at the specified 20-minute ceiling, records the timeout code, and releases locks. This is a dedicated long-duration run, not part of baseline.
2. **Stale lock reclamation:** arrange a test source lock older than 30 minutes using fixture setup, trigger a scrape, and assert the source can be acquired. Do not wait 30 minutes in k6.
3. **Webhook:** point the service to a test webhook receiver; assert completion payload operation ID/status/counts match operation telemetry. Simulate receiver non-200 responses and confirm retry behavior is visible in receiver logs (3 attempts with 5s/15s/45s backoff per endpoint contract). Do not run retry/backoff validation in the short burst profile.

## Load profiles and scenario mapping

Use the companion configuration's two profiles as follows:

- **`baseline` (1 VU):** Run API query checks throughout the profile; execute trigger and onboarding mutations at most once per test run. Run onboarding only with controlled fixture URLs. RUN-02 requires its explicit opt-in and an isolated database.
- **`unexpected_burst` (up to 5 VUs):** Focus on `RUN-03`, `RUN-04/05/06`, concurrent operation polling (`OPS`), and idempotent retry behavior. Do not create 5 simultaneous browser crawls; the service's browser concurrency remains 1.
- **Dedicated long-duration checks:** `PIPE-07` timeout and webhook backoff checks are separate runs because they exceed the short profile durations.
- Do not run destructive abort, DLQ retry, or fixture mutation scenarios concurrently against the same source/operation.

## Pass/fail criteria

- All explicit functional status, payload, idempotency, locking, cancellation, pagination, retry, and state-transition assertions above pass.
- No request in an authorized scenario receives an unexpected 5xx response.
- No operation exceeds the specified 20-minute ceiling; a controlled timeout fixture must transition to `timed_out` and release its lock.
- Numeric p95/p99 latency, error-rate, and throughput pass/fail limits are **TBD**. Use values only after they are added to [load_test_configuration.md](load_test_configuration.md); the current feature spec defines no API SLO.
- Record profile, target environment, build ID, operation IDs, HTTP status counts, request duration distributions, and webhook receiver observations for each run.

## Requirement coverage map

| Spec 2 requirements | Test definitions |
| --- | --- |
| FR-001–002 Stage 0 discovery and relevance | ONB-01–03, PIPE-03 |
| FR-003–006 async run, idempotency, locking, stale-lock recovery | RUN-01–06, PIPE-07 |
| FR-007–008 priority and domain interleaving | RUN-02/06; verify ordered/interleaved outcomes using deterministic multi-source fixtures |
| FR-009–010 browser concurrency and operation timeout | RUN-06, PIPE-07 |
| FR-011–014 templates, deterministic reuse, drift repair, schema validation | PIPE-02, PIPE-04 |
| FR-015–018 pagination, cutoff, tabs, article depth cap | PIPE-01–02 |
| FR-019–022 raw content sanitation, language, bilingual pairing, link security | PIPE-02, PIPE-03, PIPE-05 |
| FR-023–024 document ingestion/cache/file rejection and DLQ | PIPE-05–06 |
| FR-025 webhook | PIPE-07 |
| FR-026 legacy adapter removal | Not runtime-load-testable; verify with repository/static checks outside k6. |
| FR-027 sequential catalog then detail execution | RUN-01, PIPE-01–02 |
| FR-028–031 operations query and abort endpoints | API-03–07, OPS-01–08, ABT-01–06 |

