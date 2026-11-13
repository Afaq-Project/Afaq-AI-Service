// Scenario OPS-01 through OPS-08: Operation Queries & Telemetry
// Evaluates API-03 (GET /operations), API-04 (GET /operations/latest), API-05 (GET /operations/{id})

import { check, group } from 'k6';
import { httpGet, safeJson } from '../helpers.js';
import { KNOWN_OPERATION_ID } from '../config.js';

export function runOperationsScenario() {
  group('API-03, API-04, API-05: Operations Query Endpoints', function () {
    // API-03 / OPS-01: Paginated list
    const resPage1 = httpGet('/api/v1/scrape/operations?limit=2&offset=0');
    let page1Ids = [];
    check(resPage1, {
      'OPS-01: Page 1 returns 200 OK': (r) => r.status === 200,
      'OPS-01: Page 1 items length <= 2': (r) => {
        const body = safeJson(r);
        if (body && body.data && Array.isArray(body.data.operations)) {
          page1Ids = body.data.operations.map((o) => o.operation_id);
          return body.data.operations.length <= 2;
        }
        return false;
      },
      'OPS-01: Total count is non-negative integer': (r) => {
        const body = safeJson(r);
        return body && body.data && typeof body.data.total_count === 'number' && body.data.total_count >= 0;
      },
    });

    const resPage2 = httpGet('/api/v1/scrape/operations?limit=2&offset=2');
    check(resPage2, {
      'OPS-01: Page 2 returns 200 OK': (r) => r.status === 200,
      'OPS-01: Page 2 has no overlap with Page 1': (r) => {
        const body = safeJson(r);
        if (body && body.data && Array.isArray(body.data.operations)) {
          const page2Ids = body.data.operations.map((o) => o.operation_id);
          return !page2Ids.some((id) => page1Ids.includes(id));
        }
        return false;
      },
      'OPS-01: Operations are ordered descending by started_at': (r) => {
        const body = safeJson(r);
        if (body && body.data && Array.isArray(body.data.operations) && body.data.operations.length > 1) {
          const ops = body.data.operations;
          for (let i = 0; i < ops.length - 1; i++) {
            if (new Date(ops[i].started_at).getTime() < new Date(ops[i + 1].started_at).getTime()) {
              return false;
            }
          }
        }
        return Boolean(body && body.data && Array.isArray(body.data.operations));
      },
    });

    // API-03 / OPS-02: Status filter
    const resFilterCompleted = httpGet('/api/v1/scrape/operations?status=completed');
    check(resFilterCompleted, {
      'OPS-02: Filter status=completed returns 200': (r) => r.status === 200,
      'OPS-02: All records match status=completed': (r) => {
        const body = safeJson(r);
        if (body && body.data && Array.isArray(body.data.operations)) {
          return body.data.operations.every((o) => o.status === 'completed');
        }
        return false;
      },
    });

    // API-03 / OPS-03: Out-of-range offset returns 200 with empty operations list
    const resOutOfRange = httpGet('/api/v1/scrape/operations?offset=99999&limit=10');
    check(resOutOfRange, {
      'OPS-03: Out-of-range offset returns 200': (r) => r.status === 200,
      'OPS-03: Out-of-range returns empty operations array': (r) => {
        const body = safeJson(r);
        return body && body.data && Array.isArray(body.data.operations) && body.data.operations.length === 0;
      },
    });

    // API-04 / OPS-04/05/06: Latest operation
    const resLatest = httpGet('/api/v1/scrape/operations/latest');
    check(resLatest, {
      'OPS-04/05/06: Latest operation returns 200 OK': (r) => r.status === 200,
      'OPS-04/05/06: Response envelope format is valid': (r) => {
        const body = safeJson(r);
        return body && body.status === 'success' && (body.data === null || typeof body.data === 'object');
      },
    });

    // API-05 / OPS-07: Get operation by ID (known ID)
    const resKnown = httpGet(`/api/v1/scrape/operations/${KNOWN_OPERATION_ID}`);
    check(resKnown, {
      'OPS-07: Known operation returns 200 OK': (r) => r.status === 200,
      'OPS-07: Operation ID matches requested ID': (r) => {
        const body = safeJson(r);
        return body && body.data && body.data.operation_id === KNOWN_OPERATION_ID;
      },
      'OPS-07: Operation telemetry fields present': (r) => {
        const body = safeJson(r);
        return (
          body &&
          body.data &&
          typeof body.data.total_listings_found === 'number' &&
          typeof body.data.total_details_extracted === 'number'
        );
      },
    });

    // API-05 / OPS-08: Unknown UUID returns 404
    const unknownUUID = '99999999-9999-4999-8999-999999999999';
    const resUnknown = httpGet(`/api/v1/scrape/operations/${unknownUUID}`);
    check(resUnknown, {
      'OPS-08: Unknown operation UUID returns 404': (r) => r.status === 404,
    });

    // API-05: Malformed operation UUID returns 422
    const resMalformed = httpGet('/api/v1/scrape/operations/not-a-valid-uuid');
    check(resMalformed, {
      'OPS-08: Malformed operation UUID returns 422': (r) => r.status === 422,
    });
  });
}
