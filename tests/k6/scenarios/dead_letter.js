// Scenario DLQ-01 through DLQ-03: Dead Letter Queue Inspection
// Evaluates API-08 (GET /api/v1/scrape/dead-letter)

import { check, group } from 'k6';
import { httpGet, safeJson } from '../helpers.js';

export function runDeadLetterScenario() {
  group('API-08: Dead Letter Queue Inspection', function () {
    // DLQ-01: List listing failures
    const resListings = httpGet('/api/v1/scrape/dead-letter?entity_type=listings&limit=10&offset=0');
    check(resListings, {
      'DLQ-01: Listings DLQ returns 200 OK': (r) => r.status === 200,
      'DLQ-01: Entity type matches listings': (r) => {
        const body = safeJson(r);
        return body && body.data && body.data.entity_type === 'listings';
      },
      'DLQ-01: Total count is non-negative': (r) => {
        const body = safeJson(r);
        return body && body.data && typeof body.data.total_count === 'number' && body.data.total_count >= 0;
      },
    });

    // DLQ-02: List detail failures
    const resDetails = httpGet('/api/v1/scrape/dead-letter?entity_type=details&limit=10&offset=0');
    check(resDetails, {
      'DLQ-02: Details DLQ returns 200 OK': (r) => r.status === 200,
      'DLQ-02: Entity type matches details': (r) => {
        const body = safeJson(r);
        return body && body.data && body.data.entity_type === 'details';
      },
      'DLQ-02: Total count is non-negative': (r) => {
        const body = safeJson(r);
        return body && body.data && typeof body.data.total_count === 'number' && body.data.total_count >= 0;
      },
    });

    // DLQ-03: Pagination limits
    const resPaginated = httpGet('/api/v1/scrape/dead-letter?entity_type=listings&limit=1&offset=0');
    check(resPaginated, {
      'DLQ-03: Paginated limit=1 returns 200': (r) => r.status === 200,
      'DLQ-03: Returned items length <= 1': (r) => {
        const body = safeJson(r);
        return body && body.data && Array.isArray(body.data.items) && body.data.items.length <= 1;
      },
    });

    // DLQ-03: Invalid entity_type returns 422
    const resInvalidType = httpGet('/api/v1/scrape/dead-letter?entity_type=invalid_type');
    check(resInvalidType, {
      'DLQ-03: Invalid entity_type returns 422': (r) => r.status === 422,
    });
  });
}
