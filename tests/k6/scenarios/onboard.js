// Scenario ONB-01, ONB-02, ONB-03: Source Onboarding Discovery (Stage 0)
// Evaluates API-01 (POST /api/v1/scrape/sources/onboard)

import { check, group } from 'k6';
import { httpPost, safeJson } from '../helpers.js';

export function runOnboardScenario() {
  group('API-01: Source Onboarding & Stage 0 Discovery', function () {
    // ONB-03: Reject unsafe / private SSRF URLs
    const ssrfPayload = {
      url: 'http://127.0.0.1:8000/internal-resource',
      name: 'SSRF Attack Vector',
    };
    const resSSRF = httpPost('/api/v1/scrape/sources/onboard', ssrfPayload);
    check(resSSRF, {
      'ONB-03: SSRF / loopback target rejected with 422': (r) => r.status === 422,
    });

    // ONB-03: Reject malformed URL syntax
    const malformedPayload = {
      url: 'not-a-valid-url-format',
      name: 'Malformed URL Test',
    };
    const resMalformed = httpPost('/api/v1/scrape/sources/onboard', malformedPayload);
    check(resMalformed, {
      'ONB-03: Malformed URL rejected with 422': (r) => r.status === 422,
    });

    // ONB-02: Non-educational or unreachable portal rejected with 400
    // Test with a dummy domain that fails discovery or relevance
    const irrelevantPayload = {
      url: 'https://non-existent-or-commercial-domain-12345.com',
      name: 'Irrelevant Commercial Domain',
    };
    const resIrrelevant = httpPost('/api/v1/scrape/sources/onboard', irrelevantPayload);
    check(resIrrelevant, {
      'ONB-02: Irrelevant or unreachable portal rejected with 400': (r) =>
        r.status === 400 || r.status === 422,
    });
  });
}
