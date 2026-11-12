// Scenario AUTH-01: Authentication verification across all Spec 2 endpoints
// Verifies that missing or invalid API keys return 401 Unauthorized.

import { check, group } from 'k6';
import { httpGet, httpPost } from '../helpers.js';
import { KNOWN_OPERATION_ID, SOURCE_IDS } from '../config.js';

export function runAuthScenario() {
  group('AUTH-01: Missing and Invalid API Key Rejections', function () {
    const knownSourceId = SOURCE_IDS[0];
    const endpoints = [
      {
        name: 'POST /sources/onboard',
        method: 'POST',
        path: '/api/v1/scrape/sources/onboard',
        body: { url: 'https://example.edu/scholarships', name: 'Test' },
      },
      {
        name: 'POST /scrape/run',
        method: 'POST',
        path: '/api/v1/scrape/run',
        body: { source_ids: [knownSourceId] },
      },
      {
        name: 'GET /operations',
        method: 'GET',
        path: '/api/v1/scrape/operations',
      },
      {
        name: 'GET /operations/latest',
        method: 'GET',
        path: '/api/v1/scrape/operations/latest',
      },
      {
        name: 'GET /operations/{id}',
        method: 'GET',
        path: `/api/v1/scrape/operations/${KNOWN_OPERATION_ID}`,
      },
      {
        name: 'POST /operations/{id}/abort',
        method: 'POST',
        path: `/api/v1/scrape/operations/${KNOWN_OPERATION_ID}/abort`,
        body: {},
      },
      {
        name: 'POST /sources/{id}/abort',
        method: 'POST',
        path: `/api/v1/scrape/sources/${knownSourceId}/abort`,
        body: {},
      },
      {
        name: 'GET /dead-letter',
        method: 'GET',
        path: '/api/v1/scrape/dead-letter',
      },
    ];

    for (const ep of endpoints) {
      // 1. Missing API Key
      let resMissing = ep.method === 'GET'
        ? httpGet(ep.path, null)
        : httpPost(ep.path, ep.body || {}, null);

      check(resMissing, {
        [`${ep.name} (missing key) returns 401`]: (r) => r.status === 401,
      });

      // 2. Invalid API Key
      let resInvalid = ep.method === 'GET'
        ? httpGet(ep.path, 'invalid-key-99999')
        : httpPost(ep.path, ep.body || {}, 'invalid-key-99999');

      check(resInvalid, {
        [`${ep.name} (invalid key) returns 401`]: (r) => r.status === 401,
      });
    }
  });
}
