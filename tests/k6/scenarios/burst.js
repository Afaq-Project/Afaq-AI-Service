// Scenario RUN-03 Burst & RUN-06: Concurrent Triggers and Burst Testing
// Evaluates concurrent idempotent retries and concurrent operation requests under 5 VUs

import { check, group } from 'k6';
import { httpBatchPost, httpGet, safeJson, uuidv4 } from '../helpers.js';
import { LOCKED_SOURCE_ID, SOURCE_IDS } from '../config.js';

export function runBurstScenario() {
  // Use one k6 VU to send a five-request HTTP batch. This allows all returned
  // operation IDs to be compared in one VU while keeping concurrent triggers
  // at the configured maximum of five. The mutation runs only once; remaining
  // iterations exercise read-only polling.
  if (__VU === 1 && __ITER === 0) {
    group('RUN-03: Five simultaneous retries with the same idempotency key', function () {
      const sharedIdempKey = uuidv4();
      const requests = Array.from({ length: 5 }, () => ({
        body: { source_ids: [SOURCE_IDS[0]] },
        headers: { 'Idempotency-Key': sharedIdempKey },
      }));
      const responses = httpBatchPost('/api/v1/scrape/run', requests);
      const bodies = responses.map(safeJson);
      const operationIds = bodies.map((body) => body && body.operation_id);
      const statuses = responses.map((response) => response.status);
      if (statuses.some((status) => status !== 202 && status !== 200)) {
        console.error(
          `RUN-03 concurrent retry responses: ${JSON.stringify(
            responses.map((response, index) => ({
              status: response.status,
              operationId: operationIds[index] || null,
              body: bodies[index],
            }))
          )}`
        );
      }

      check(responses, {
        'RUN-03: all concurrent retries return accepted or deduplicated status': (items) =>
          items.length === 5 && items.every((item) => item.status === 202 || item.status === 200),
        'RUN-03: every retry returns the same valid operation_id': () => {
          const firstId = operationIds[0];
          return (
            typeof firstId === 'string' &&
            /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(firstId) &&
            operationIds.every((operationId) => operationId === firstId)
          );
        },
        'RUN-03: exactly one request creates the operation': () =>
          statuses.filter((status) => status === 202).length === 1 &&
          statuses.filter((status) => status === 200).length === 4,
      });
    });

    group('RUN-06: distinct valid keys are rejected for a locked source', function () {
      const requests = Array.from({ length: 5 }, () => ({
        body: { source_ids: [LOCKED_SOURCE_ID] },
        headers: { 'Idempotency-Key': uuidv4() },
      }));
      const responses = httpBatchPost('/api/v1/scrape/run', requests);

      check(responses, {
        'RUN-06: all distinct-key requests receive 409 for the locked source': (items) =>
          items.length === 5 && items.every((item) => item.status === 409),
      });
    });
  }

  // Keep the five-VU profile active with read-only operation polling after the
  // one-shot mutation batch; do not create new operations on every iteration.
  const resOps = httpGet('/api/v1/scrape/operations?limit=5');
  check(resOps, {
    'OPS: Concurrent operations polling returns 200': (response) => response.status === 200,
  });

  const resLatest = httpGet('/api/v1/scrape/operations/latest');
  check(resLatest, {
    'OPS: Concurrent latest polling returns 200': (response) => response.status === 200,
  });
}
