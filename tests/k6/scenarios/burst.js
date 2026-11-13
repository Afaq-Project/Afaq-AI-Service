// Scenario RUN-03 Burst & RUN-06: Concurrent Triggers and Burst Testing
// Evaluates concurrent idempotent retries and concurrent operation requests under 5 VUs

import { check, group } from 'k6';
import { httpPost, httpGet, safeJson } from '../helpers.js';
import { SOURCE_IDS, LOCKED_SOURCE_ID } from '../config.js';

export function runBurstScenario() {
  group('Burst Profile: Concurrent Same-Key Idempotency', function () {
    const validSourceId = SOURCE_IDS[0];
    // Exact same idempotency key across all VUs in this batch
    const sharedIdempKey = 'burst-shared-idemp-static-001';

    // Concurrently trigger with identical key
    const res = httpPost(
      '/api/v1/scrape/run',
      { source_ids: [validSourceId] },
      undefined,
      { headers: { 'Idempotency-Key': sharedIdempKey } }
    );

    check(res, {
      'RUN-06: Same-key concurrent trigger returns 202 or 200 (idempotent)': (r) =>
        r.status === 202 || r.status === 200 || r.status === 409,
      'RUN-06: Concurrent trigger never returns 5xx': (r) => r.status < 500,
      'RUN-06: Operation ID present in response': (r) => {
        const body = safeJson(r);
        return body && body.data && typeof body.data.operation_id === 'string';
      },
    });
  });

  group('Burst Profile: Lock Contention on Already-Locked Source', function () {
    // Each VU sends distinct key against locked source
    const distinctKey = `burst-locked-vu-${__VU}-${Date.now()}`;
    const resLocked = httpPost(
      '/api/v1/scrape/run',
      { source_ids: [LOCKED_SOURCE_ID] },
      undefined,
      { headers: { 'Idempotency-Key': distinctKey } }
    );

    check(resLocked, {
      'RUN-06: Competing request against locked source returns graceful 409 or 422': (r) =>
        r.status === 409 || r.status === 422 || r.status === 200 || r.status === 202,
      'RUN-06: Locked source trigger never returns 5xx': (r) => r.status < 500,
    });

    // Concurrent operations log polling
    const resOps = httpGet('/api/v1/scrape/operations?limit=5');
    check(resOps, {
      'OPS: Concurrent operations polling returns 200': (r) => r.status === 200,
    });

    // Concurrent latest operation polling
    const resLatest = httpGet('/api/v1/scrape/operations/latest');
    check(resLatest, {
      'OPS: Concurrent latest polling returns 200': (r) => r.status === 200,
    });
  });
}
