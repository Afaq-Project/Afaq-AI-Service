// Scenario ABT-01 through ABT-06: Operation & Source Abort Controls
// Evaluates API-06 (POST /operations/{id}/abort) and API-07 (POST /sources/{id}/abort)

import { check, group } from 'k6';
import { httpPost } from '../helpers.js';
import { KNOWN_OPERATION_ID, INACTIVE_SOURCE_ID } from '../config.js';

export function runAbortScenario() {
  group('API-06 & API-07: Abort Operations and Sources', function () {
    const unknownUUID = '99999999-9999-4999-8999-999999999999';

    // API-06 / ABT-02: Abort terminal operation returns 400 Bad Request
    const resTerminal = httpPost(`/api/v1/scrape/operations/${KNOWN_OPERATION_ID}/abort`, {});
    check(resTerminal, {
      'ABT-02: Abort already completed operation returns 400': (r) => r.status === 400,
    });

    // API-06 / ABT-03: Abort unknown operation returns 404 Not Found
    const resUnknownOp = httpPost(`/api/v1/scrape/operations/${unknownUUID}/abort`, {});
    check(resUnknownOp, {
      'ABT-03: Abort unknown operation returns 404': (r) => r.status === 404,
    });

    // API-06: Abort malformed operation UUID returns 422
    const resMalformedOp = httpPost('/api/v1/scrape/operations/not-a-valid-uuid/abort', {});
    check(resMalformedOp, {
      'ABT-03: Abort malformed operation UUID returns 422': (r) => r.status === 422,
    });

    // API-07 / ABT-05: Abort inactive/unlocked source returns 400 Bad Request
    const resInactiveSrc = httpPost(`/api/v1/scrape/sources/${INACTIVE_SOURCE_ID}/abort`, {});
    check(resInactiveSrc, {
      'ABT-05: Abort inactive source returns 400': (r) => r.status === 400,
    });

    // API-07 / ABT-06: Abort unknown source returns 404 Not Found
    const resUnknownSrc = httpPost(`/api/v1/scrape/sources/${unknownUUID}/abort`, {});
    check(resUnknownSrc, {
      'ABT-06: Abort unknown source returns 404': (r) => r.status === 404,
    });

    // API-07: Abort malformed source UUID returns 422
    const resMalformedSrc = httpPost('/api/v1/scrape/sources/not-a-valid-uuid/abort', {});
    check(resMalformedSrc, {
      'ABT-06: Abort malformed source UUID returns 422': (r) => r.status === 422,
    });
  });
}
