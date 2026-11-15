// Scenario ONB-01, ONB-02, ONB-03: Source Onboarding Discovery (Stage 0)
// Evaluates API-01 (POST /api/v1/scrape/sources/onboard)

import { check, group } from 'k6';
import { httpPost, safeJson, uuidv4 } from '../helpers.js';
import {
  ENABLE_ONBOARDING,
  TEST_IRRELEVANT_PORTAL_URL,
  TEST_VALID_PORTAL_URL,
} from '../config.js';

export function runOnboardScenario() {
  // Onboarding mutates data and can invoke DNS, crawling, and LLM services.
  // Run it once against operator-provided controlled fixtures, not once per
  // baseline iteration or against an arbitrary public hostname.
  if (__ITER !== 0) return;

  group('API-01: Source Onboarding & Stage 0 Discovery', function () {
    if (ENABLE_ONBOARDING) {
      const validPayload = {
        url: TEST_VALID_PORTAL_URL,
        name: `k6-controlled-valid-${uuidv4()}`,
      };
      const resValid = httpPost('/api/v1/scrape/sources/onboard', validPayload);
      check(resValid, {
        'ONB-01: Controlled educational portal returns 200': (r) => r.status === 200,
        'ONB-01: Response includes source and discovery data': (r) => {
          const body = safeJson(r);
          return Boolean(
            body &&
              body.status === 'success' &&
              body.data &&
              typeof body.data.source_id === 'string' &&
              body.data.source_id.length > 0
          );
        },
      });
    } else {
      console.warn(
        'BLOCKED: ONB-01/ONB-02 require operator-supplied controlled portal fixtures; only SSRF and malformed-URL checks will run.'
      );
    }

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
    if (ENABLE_ONBOARDING) {
      const irrelevantPayload = {
        url: TEST_IRRELEVANT_PORTAL_URL,
        name: `k6-controlled-irrelevant-${uuidv4()}`,
      };
      const resIrrelevant = httpPost('/api/v1/scrape/sources/onboard', irrelevantPayload);
      check(resIrrelevant, {
        'ONB-02: Controlled irrelevant portal rejected with 400': (r) => r.status === 400,
      });
    }
  });
}
