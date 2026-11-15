// Scenario RUN-01 through RUN-05: Scrape Run Triggering & Idempotency
// Evaluates API-02 (POST /api/v1/scrape/run)

import { check, group, sleep } from 'k6';
import { httpPost, httpGet, safeJson, uuidv4 } from '../helpers.js';
import {
  ENABLE_OMITTED_SOURCE_IDS,
  POLLING_INTERVAL_SEC,
  SOURCE_IDS,
  LOCKED_SOURCE_ID,
} from '../config.js';

export function runScrapeTriggerScenario() {
  // Triggering starts background crawls and acquires locks. In the baseline
  // profile, mutate fixtures only in the first VU iteration; later iterations
  // continue exercising the read-only operation endpoints.
  if (__ITER !== 0) return;

  group('API-02: Trigger Scraping & Concurrency Controls', function () {
    const validSourceId = SOURCE_IDS[0];

    // RUN-04: Malformed UUID in source_ids returns 422
    const resMalformedSource = httpPost(
      '/api/v1/scrape/run',
      { source_ids: ['invalid-not-a-uuid'] },
      undefined,
      { headers: { 'Idempotency-Key': uuidv4() } }
    );
    check(resMalformedSource, {
      'RUN-04: Malformed source_id rejected with 422': (r) => r.status === 422,
    });

    // RUN-04: Malformed Idempotency-Key header returns 422
    const resMalformedIdemp = httpPost(
      '/api/v1/scrape/run',
      { source_ids: [validSourceId] },
      undefined,
      { headers: { 'Idempotency-Key': 'not-a-valid-uuid-header' } }
    );
    check(resMalformedIdemp, {
      'RUN-04: Malformed Idempotency-Key rejected with 422': (r) => r.status === 422,
    });

    // RUN-05: All requested sources locked returns 409 Conflict
    const resLocked = httpPost(
      '/api/v1/scrape/run',
      { source_ids: [LOCKED_SOURCE_ID] },
      undefined,
      { headers: { 'Idempotency-Key': uuidv4() } }
    );
    check(resLocked, {
      'RUN-05: Locked target source rejected with 409': (r) => r.status === 409,
    });

    // RUN-01: Trigger one valid source with fresh idempotency key
    const idempKey = uuidv4();
    const resRun = httpPost(
      '/api/v1/scrape/run',
      { source_ids: [validSourceId] },
      undefined,
      { headers: { 'Idempotency-Key': idempKey } }
    );

    let initialOpId = null;
    const isAccepted = check(resRun, {
      'RUN-01: Valid source trigger returns 202 Accepted': (r) => r.status === 202,
      'RUN-01: Response status is accepted': (r) => {
        const body = safeJson(r);
        return body && body.status === 'accepted';
      },
      'RUN-01: Valid operation_id returned': (r) => {
        const body = safeJson(r);
        if (body && body.operation_id) {
          initialOpId = body.operation_id;
          return true;
        }
        return false;
      },
    });

    // RUN-03: immediately retry the same logical request while its operation
    // is running (or has just completed).
    const resDuplicate = httpPost(
      '/api/v1/scrape/run',
      { source_ids: [validSourceId] },
      undefined,
      { headers: { 'Idempotency-Key': idempKey } }
    );

    check(resDuplicate, {
      'RUN-03: Repeated idempotency key returns 200 OK': (r) => r.status === 200,
      'RUN-03: Returned operation_id matches original': (r) => {
        const body = safeJson(r);
        return Boolean(body && body.operation_id === initialOpId);
      },
      'RUN-03: Response acknowledges existing operation': (r) => {
        const body = safeJson(r);
        return Boolean(body && body.status === 'accepted');
      },
    });

    // RUN-01 telemetry: the operation endpoint wraps its record in data.
    if (initialOpId) {
      let pollObserved = false;
      let terminalStatus = false;
      const terminalStatuses = new Set([
        'completed',
        'partial',
        'failed',
        'timed_out',
        'aborted',
      ]);
      for (let attempt = 0; attempt < 5 && !terminalStatus; attempt++) {
        sleep(POLLING_INTERVAL_SEC);
        const resPoll = httpGet(`/api/v1/scrape/operations/${initialOpId}`);
        if (resPoll.status === 200) {
          const pollBody = safeJson(resPoll);
          if (pollBody && pollBody.data && pollBody.data.operation_id === initialOpId) {
            pollObserved = true;
            terminalStatus = terminalStatuses.has(pollBody.data.status);
          }
        }
      }
      check(null, {
        'RUN-01: Operation status polling returns matching operation_id': () => pollObserved,
        'RUN-01: Controlled operation reaches a terminal state during polling': () => terminalStatus,
      });
    }

    // RUN-02 targets every active source. Run it only when the operator opts
    // into a dedicated test database containing test sources exclusively.
    if (ENABLE_OMITTED_SOURCE_IDS) {
      const resOmitted = httpPost(
        '/api/v1/scrape/run',
        {},
        undefined,
        { headers: { 'Idempotency-Key': uuidv4() } }
      );

      check(resOmitted, {
        'RUN-02: Omitted source_ids returns 202 Accepted': (r) => r.status === 202,
        'RUN-02: Omitted source_ids returns operation_id': (r) => {
          const body = safeJson(r);
          return Boolean(body && body.operation_id);
        },
      });
    }
  });
}
