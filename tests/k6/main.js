// Main k6 Test Suite for Spec 2 Scraping and Extraction Pipeline
// Implements load_test_configuration.md and k6_test_definition.md

import { sleep } from 'k6';
import { PROFILE, PROFILES } from './config.js';
import { runAuthScenario } from './scenarios/auth.js';
import { runOnboardScenario } from './scenarios/onboard.js';
import { runScrapeTriggerScenario } from './scenarios/run.js';
import { runOperationsScenario } from './scenarios/operations.js';
import { runAbortScenario } from './scenarios/abort.js';
import { runDeadLetterScenario } from './scenarios/dead_letter.js';
import { runBurstScenario } from './scenarios/burst.js';

const selectedProfile = PROFILES[PROFILE];
if (!selectedProfile) {
  throw new Error(`Unknown K6_PROFILE '${PROFILE}'. Choose baseline or unexpected_burst.`);
}

export const options = {
  stages: selectedProfile.stages,
  thresholds: {
    // Numeric percentiles and error SLOs remain unset as marked TBD in load_test_configuration.md
    // Functional checks must all pass. Expected 4xx rejection cases are checks,
    // not server failures, so track 5xx responses in their own custom metric.
    checks: ['rate==1'],
    http_5xx_rate: ['rate==0'],
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
