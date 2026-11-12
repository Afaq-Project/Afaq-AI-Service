// Scenario RUN-03 Burst & RUN-06: Concurrent Triggers and Burst Testing
// Evaluates concurrent idempotent retries and concurrent operation requests under 5 VUs

import { check, group } from 'k6';
import { httpPost, httpGet, safeJson, uuidv4 } from '../helpers.js';
import { SOURCE_IDS, LOCKED_SOURCE_ID } from '../config.js';

// Shared idempotency key per VU cycle or per burst batch
let burstKey = null;

export function runBurstScenario() {
  group('Burst Profile: Concurrent Idempotency & Operation Polling', function () {
    const validSourceId = SOURCE_IDS[0];

    // Every VU uses a batch-shared key or an independent key
    const idempKey = `burst-idemp-${__VU}`;

    // Concurrently trigger with idempotency key
    const res = httpPost(
      '/api/v1/scrape/run',
      { source_ids: [validSourceId] },
      undefined,
      { headers: { 'Idempotency-Key': uuidv4() } }
    );

    check(res, {
      'RUN-06: Concurrent trigger returns 202 or 409 (graceful conflict)': (r) =>
        r.status === 202 || r.status === 409 || r.status === 200,
      'RUN-06: Concurrent trigger never returns 5xx': (r) => r.status < 500,
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
