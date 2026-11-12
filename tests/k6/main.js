// Main k6 Test Suite for Spec 2 Scraping and Extraction Pipeline
// Implements load_test_configuration.md and k6_test_definition.md

import { sleep } from 'k6';
import { PROFILE, PROFILES, REQUEST_TIMEOUT } from './config.js';
import { runAuthScenario } from './scenarios/auth.js';
import { runOnboardScenario } from './scenarios/onboard.js';
import { runScrapeTriggerScenario } from './scenarios/run.js';
import { runOperationsScenario } from './scenarios/operations.js';
import { runAbortScenario } from './scenarios/abort.js';
import { runDeadLetterScenario } from './scenarios/dead_letter.js';
import { runBurstScenario } from './scenarios/burst.js';

const selectedProfile = PROFILES[PROFILE] || PROFILES.baseline;

export const options = {
  stages: selectedProfile.stages,
  thresholds: {
    // Numeric percentiles and error SLOs remain unset as marked TBD in load_test_configuration.md
    // Service-level assertion: No unhandled 5xx errors across authorized endpoints
    'http_req_failed{status:500}': ['rate==0'],
  },
  tags: {
    environment: __ENV.K6_ENVIRONMENT || 'test',
    build_id: __ENV.K6_BUILD_ID || 'local',
    profile: PROFILE,
  },
};

export default function () {
  if (PROFILE === 'unexpected_burst') {
    // Burst profile: Focus on concurrent triggers, idempotent retries, and high-frequency polling
    runBurstScenario();
    sleep(1);
  } else {
    // Baseline profile: Run API query checks, trigger/idempotency, onboarding, abort, and DLQ
    runAuthScenario();
    runOnboardScenario();
    runScrapeTriggerScenario();
    runOperationsScenario();
    runAbortScenario();
    runDeadLetterScenario();
    sleep(1);
  }
}
