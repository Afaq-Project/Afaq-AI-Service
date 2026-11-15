# Postponed k6 Scenarios: Source Onboarding

**Status:** Postponed; not executed in the Codespaces run on 2026-11-15.

**Reason:** No operator-controlled portal fixtures were configured. These checks perform live onboarding discovery, so arbitrary public websites are not suitable substitutes.

## Scenarios

| ID | Purpose | Required fixture | Expected result |
| --- | --- | --- | --- |
| ONB-01 | Onboard a valid educational portal through `POST /api/v1/scrape/sources/onboard`. | A reachable, operator-controlled educational portal with stable pages and public opportunity content. | `200`; successful response with a source ID and discovery data. |
| ONB-02 | Reject a reachable portal that is not an educational opportunity source through the same endpoint. | A reachable, operator-controlled irrelevant portal whose content should fail the relevance gate. | `400`; portal is rejected and not onboarded. |

The implemented checks are in [`tests/k6/scenarios/onboard.js`](../../../tests/k6/scenarios/onboard.js). They run once in the baseline profile when explicitly enabled. Without fixtures, the script reports both as `BLOCKED`; this is separate from ONB-03's SSRF and malformed-URL checks, which do run.

## Fixture requirements

- Supply both URLs through `K6_TEST_VALID_PORTAL_URL` and `K6_TEST_IRRELEVANT_PORTAL_URL`.
- Use hosts and pages controlled by the project or its operator, reachable from the Codespace, and safe for repeated reads.
- Keep the valid portal stable and representative of public educational opportunities. Keep the irrelevant portal reachable while ensuring its content should be rejected by the relevance gate.
- Use the isolated, non-production Codespaces database. Onboarding can create source records and perform discovery; reset or reseed the test database between repeated runs if necessary.
- Do not use production portals, arbitrary third-party sites, or content that requires authentication, bypassing access controls, or evading bot protections.

## How to resume

In the Codespace, export the fixture settings and run the k6 tier:

```bash
export K6_ENABLE_ONBOARDING=true
export K6_TEST_VALID_PORTAL_URL='https://<controlled-valid-fixture>'
export K6_TEST_IRRELEVANT_PORTAL_URL='https://<controlled-irrelevant-fixture>'
bash scripts/codespaces_test.sh k6
```

The command runs both baseline and unexpected-burst profiles; onboarding mutations occur only once in the baseline profile. Confirm the report no longer labels ONB-01/ONB-02 `BLOCKED`, and that both assertions pass. Do not mark these scenarios complete based only on a successful run of the other k6 checks.
