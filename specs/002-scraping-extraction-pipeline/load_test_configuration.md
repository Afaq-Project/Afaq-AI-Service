# k6 Load Test Configuration

This file stores load-test settings for the scraping API. The agent should read these values when creating or updating the base k6 configuration. It defines configuration only; request flows and test scenarios belong elsewhere.

## Service context

- **Service role:** Backend worker API called by the primary system; assume one normal client/user.
- **Normal concurrency:** One virtual user (VU).
- **Unexpected usage to account for:** Concurrent retries or duplicate requests, overlapping scrape triggers, and operation-status polling. Spec 2 explicitly requires idempotency handling and safe locking when requests overlap.
- **Crawler constraint:** The service is specified to run one browser crawl at a time per instance. Do not interpret higher API VU counts as permission to run concurrent browser sessions.
- **Target:** Set `K6_BASE_URL` to the deployed test environment. Do not target production unless the operator explicitly configures it.

## Profiles

Values below are initial configuration defaults. Keep profile settings independently selectable in the generated k6 configuration.

| Setting | `baseline` | `unexpected_burst` |
| --- | ---: | ---: |
| Virtual users | 1 | 5 |
| Ramp-up | 10 seconds | 10 seconds |
| Steady state | 5 minutes | 1 minute |
| Ramp-down | 10 seconds | 10 seconds |
| Max test duration | 5 minutes 20 seconds | 1 minute 20 seconds |
| Max concurrent scrape-trigger requests | 1 | 5 |

The burst profile represents a single primary-system client producing retries or overlapping requests; it is not a many-user public workload target.

## Request and polling settings

- **HTTP request timeout:** 30 seconds.
- **Operation polling interval:** 5 seconds.
- **Operation polling maximum duration:** 20 minutes, matching the spec's scrape-operation timeout ceiling.
- **Idempotency retry window:** 15 minutes, matching Spec 2. Repeated trigger attempts in a generated test must reuse the same idempotency key when modeling a retry of the same request.
- **Request rate:** Derive from the selected VU profile and scenario iteration behavior; do not add an independent constant-arrival-rate workload without an explicit update to this file.

## Acceptance thresholds

The following thresholds need an agreed service SLO before the agent can turn them into k6 pass/fail thresholds:

- **Response-time percentiles:** TBD (at minimum p95 and p99).
- **HTTP error-rate ceiling:** TBD.
- **Minimum throughput:** TBD, if required for a profile.

Keep these unset in the generated k6 pass/fail thresholds until values are supplied. The service specification defines asynchronous `202 Accepted` trigger behavior and a 20-minute job ceiling, but does not define API latency or error-rate SLOs.

## Environment and credentials

- **Base URL:** `K6_BASE_URL` (required; no default production URL).
- **API key:** `K6_API_KEY` (required; inject through environment variables, never store the secret here).
- **Source IDs:** `K6_SOURCE_IDS` (test-environment UUIDs only; do not place production identifiers here).
- **TLS verification:** Enabled by default.
- **Run labels:** `K6_ENVIRONMENT`, `K6_BUILD_ID`, and selected profile name.

## Resource and safety limits

- **Maximum VUs:** 5.
- **Maximum concurrent scrape triggers:** 5.
- **Maximum request timeout:** 30 seconds.
- **Browser concurrency:** 1 per service instance, per Spec 2.
- Use dedicated test sources and a non-production environment. Avoid expanding load beyond these limits without reviewing the service's 1 GB memory constraint and target-site rate limits.
