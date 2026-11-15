// Load test configuration adhering to load_test_configuration.md and spec 2

function requiredEnv(name) {
  const value = __ENV[name];
  if (!value) {
    throw new Error(`Missing required k6 environment variable: ${name}`);
  }
  return value;
}

function requireUuid(name, value) {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)) {
    throw new Error(`${name} must be a valid UUID`);
  }
  return value;
}

export const BASE_URL = requiredEnv('K6_BASE_URL').replace(/\/+$/, '');
export const API_KEY = requiredEnv('K6_API_KEY');
export const PROFILE = __ENV.K6_PROFILE || 'baseline';
if (!['baseline', 'unexpected_burst'].includes(PROFILE)) {
  throw new Error(`Unknown K6_PROFILE '${PROFILE}'. Choose baseline or unexpected_burst.`);
}

export const SOURCE_IDS = requiredEnv('K6_SOURCE_IDS')
  .split(',')
  .map((sourceId) => requireUuid('K6_SOURCE_IDS entry', sourceId.trim()));
export const LOCKED_SOURCE_ID = requireUuid(
  'K6_LOCKED_SOURCE_ID',
  requiredEnv('K6_LOCKED_SOURCE_ID')
);
export const INACTIVE_SOURCE_ID = requireUuid(
  'K6_INACTIVE_SOURCE_ID',
  requiredEnv('K6_INACTIVE_SOURCE_ID')
);
export const KNOWN_OPERATION_ID = requireUuid(
  'K6_KNOWN_OPERATION_ID',
  requiredEnv('K6_KNOWN_OPERATION_ID')
);

// Dedicated, controlled onboarding fixtures are optional. Positive/relevance
// checks stay BLOCKED unless an operator explicitly enables them with URLs.
export const ENABLE_ONBOARDING = __ENV.K6_ENABLE_ONBOARDING === 'true';
export const TEST_VALID_PORTAL_URL = __ENV.K6_TEST_VALID_PORTAL_URL || '';
export const TEST_IRRELEVANT_PORTAL_URL =
  __ENV.K6_TEST_IRRELEVANT_PORTAL_URL || '';
if (ENABLE_ONBOARDING && (!TEST_VALID_PORTAL_URL || !TEST_IRRELEVANT_PORTAL_URL)) {
  throw new Error(
    'K6_ENABLE_ONBOARDING=true requires K6_TEST_VALID_PORTAL_URL and K6_TEST_IRRELEVANT_PORTAL_URL controlled fixtures'
  );
}

export const ENABLE_OMITTED_SOURCE_IDS =
  __ENV.K6_ENABLE_OMITTED_SOURCE_IDS === 'true';

// Profile stage configurations per load_test_configuration.md
export const PROFILES = {
  baseline: {
    vus: 1,
    stages: [
      { duration: __ENV.K6_RAMP_UP || '10s', target: 1 },
      { duration: __ENV.K6_STEADY || '5m', target: 1 },
      { duration: __ENV.K6_RAMP_DOWN || '10s', target: 0 },
    ],
    maxDuration: '5m20s',
  },
  unexpected_burst: {
    vus: 5,
    stages: [
      { duration: __ENV.K6_RAMP_UP || '10s', target: 5 },
      { duration: __ENV.K6_STEADY || '1m', target: 5 },
      { duration: __ENV.K6_RAMP_DOWN || '10s', target: 0 },
    ],
    maxDuration: '1m20s',
  },
};

export const REQUEST_TIMEOUT = '30s';
export const POLLING_INTERVAL_SEC = 5;
export const POLLING_MAX_DURATION_SEC = 1200; // 20 minutes
