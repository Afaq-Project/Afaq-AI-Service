// Load test configuration adhering to load_test_configuration.md and spec 2

export const BASE_URL = __ENV.K6_BASE_URL || 'http://127.0.0.1:8000';
export const API_KEY = __ENV.K6_API_KEY || 'k6-test-key-secret-12345';
export const SOURCE_IDS = (__ENV.K6_SOURCE_IDS || '22222222-2222-4222-8222-222222222222').split(',');
export const LOCKED_SOURCE_ID = __ENV.K6_LOCKED_SOURCE_ID || '33333333-3333-4333-8333-333333333333';
export const INACTIVE_SOURCE_ID = __ENV.K6_INACTIVE_SOURCE_ID || '44444444-4444-4444-4444-444444444444';
export const KNOWN_OPERATION_ID = __ENV.K6_KNOWN_OPERATION_ID || '11111111-1111-4111-8111-111111111111';

export const PROFILE = __ENV.K6_PROFILE || 'baseline';

// Profile stage configurations per load_test_configuration.md
export const PROFILES = {
  baseline: {
    vus: 1,
    stages: [
      { duration: __ENV.K6_RAMP_UP || '10s', target: 1 },
      { duration: __ENV.K6_STEADY || '30s', target: 1 },
      { duration: __ENV.K6_RAMP_DOWN || '10s', target: 0 },
    ],
    maxDuration: '5m20s',
  },
  unexpected_burst: {
    vus: 5,
    stages: [
      { duration: __ENV.K6_RAMP_UP || '10s', target: 5 },
      { duration: __ENV.K6_STEADY || '30s', target: 5 },
      { duration: __ENV.K6_RAMP_DOWN || '10s', target: 0 },
    ],
    maxDuration: '1m20s',
  },
};

export const REQUEST_TIMEOUT = '30s';
export const POLLING_INTERVAL_SEC = 5;
export const POLLING_MAX_DURATION_SEC = 1200; // 20 minutes
