#!/usr/bin/env bash
# Risk-tiered test runner for Codespaces' isolated native PostgreSQL setup.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

MODE="${1:-all}"
TEST_ENV_FILE="${CODESPACES_TEST_ENV_FILE:-${HOME}/.config/afaq-ai-service/codespaces-test.env}"
COMMIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
BRANCH_NAME="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"

case "${MODE}" in
    unit|contracts|postgres|browser|boundary|smoke|k6|all) ;;
    *)
        echo "ERROR: Unsupported mode. Use unit, contracts, postgres, browser, boundary, smoke, k6, or all." >&2
        exit 2
        ;;
esac

needs_database=false
case "${MODE}" in
    postgres|smoke|k6|all) needs_database=true ;;
esac

if [[ -f "${TEST_ENV_FILE}" ]]; then
    env_mode="$(stat -c '%a' "${TEST_ENV_FILE}")"
    if [[ "${env_mode}" != 600 && "${env_mode}" != 400 ]]; then
        echo "ERROR: Codespaces test environment file must have mode 0600 or 0400." >&2
        exit 1
    fi
    # Only load the private local test configuration created by setup.
    # shellcheck source=/dev/null
    source "${TEST_ENV_FILE}"
elif [[ "${needs_database}" == "true" ]]; then
    echo "ERROR: Isolated test configuration is missing. Run scripts/codespaces_test_setup.sh first." >&2
    exit 2
fi

if [[ "${needs_database}" == "true" ]]; then
    : "${TEST_DB_NAME:?Test setup is missing TEST_DB_NAME}"
    : "${TEST_DB_USER:?Test setup is missing TEST_DB_USER}"
    : "${TEST_DB_PORT:?Test setup is missing TEST_DB_PORT}"
    : "${DATABASE_URL:?Test setup is missing DATABASE_URL}"
    : "${DIRECT_URL:?Test setup is missing DIRECT_URL}"
    : "${TEST_API_KEY:?Test setup is missing TEST_API_KEY}"
    if ! DATABASE_URL="${DATABASE_URL}" DIRECT_URL="${DIRECT_URL}" \
        TEST_DB_NAME="${TEST_DB_NAME}" TEST_DB_USER="${TEST_DB_USER}" \
        TEST_DB_PORT="${TEST_DB_PORT}" uv run python - <<'PY'
import os
from urllib.parse import urlsplit

expected_db = os.environ["TEST_DB_NAME"]
expected_user = os.environ["TEST_DB_USER"]
expected_port = int(os.environ["TEST_DB_PORT"])
loopback_hosts = {"localhost", "127.0.0.1", "::1"}

for name in ("DATABASE_URL", "DIRECT_URL"):
    parsed = urlsplit(os.environ[name])
    actual_db = parsed.path.lstrip("/")
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or parsed.hostname not in loopback_hosts
        or parsed.port != expected_port
        or parsed.username != expected_user
        or actual_db != expected_db
        or not actual_db.endswith("_test")
    ):
        raise SystemExit(1)
if os.environ["DATABASE_URL"] != os.environ["DIRECT_URL"]:
    raise SystemExit(1)
PY
    then
        echo "ERROR: Database configuration is not the exact local isolated test target; values were not printed." >&2
        exit 2
    fi
    export ENVIRONMENT=test
    export LOG_LEVEL="${LOG_LEVEL:-INFO}"
fi

echo "=========================================================="
echo "Afaq AI Service - Codespaces Test Runner"
echo "Commit: ${COMMIT_SHA} (${BRANCH_NAME})"
echo "Mode:   ${MODE}"
echo "=========================================================="

UVICORN_PID=""
UVICORN_LOG=""
cleanup() {
    if [[ -n "${UVICORN_PID}" ]]; then
        if kill -0 "-${UVICORN_PID}" 2>/dev/null; then
            kill -TERM -- "-${UVICORN_PID}" 2>/dev/null || true
            for _ in $(seq 1 20); do
                kill -0 "-${UVICORN_PID}" 2>/dev/null || break
                sleep 0.25
            done
            kill -KILL -- "-${UVICORN_PID}" 2>/dev/null || true
        fi
        wait "${UVICORN_PID}" 2>/dev/null || true
        echo "Stopped test API process group ${UVICORN_PID}."
    fi
    if [[ -n "${UVICORN_LOG}" ]]; then
        rm -f -- "${UVICORN_LOG}"
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

start_api_server() {
    local api_port="${TEST_API_PORT:-8000}"
    if [[ ! "${api_port}" =~ ^[0-9]{1,5}$ ]] || (( api_port < 1024 || api_port > 65535 )); then
        echo "ERROR: TEST_API_PORT must be an unprivileged TCP port." >&2
        return 2
    fi
    if curl -fsS --max-time 1 "http://127.0.0.1:${api_port}/health" >/dev/null 2>&1; then
        echo "ERROR: A service already answers on TEST_API_PORT=${api_port}; refusing to use or stop an unowned server." >&2
        return 2
    fi
    if ! command -v setsid >/dev/null 2>&1; then
        echo "ERROR: 'setsid' is required so cleanup can stop only the server started by this script." >&2
        return 2
    fi

    UVICORN_LOG="$(mktemp "${TMPDIR:-/tmp}/afaq-test-api.XXXXXX.log")"
    echo "Starting the test API on 127.0.0.1:${api_port}."
    setsid uv run uvicorn src.main:app --host 127.0.0.1 --port "${api_port}" \
        --log-level warning >"${UVICORN_LOG}" 2>&1 &
    UVICORN_PID=$!

    for _ in $(seq 1 120); do
        if curl -fsS --max-time 1 "http://127.0.0.1:${api_port}/health" >/dev/null 2>&1; then
            echo "Test API health check passed."
            return 0
        fi
        if ! kill -0 "-${UVICORN_PID}" 2>/dev/null; then
            echo "ERROR: Test API process exited before becoming healthy; sanitized log retained at ${UVICORN_LOG}." >&2
            return 1
        fi
        sleep 1
    done
    echo "ERROR: Test API did not become healthy; sanitized log retained at ${UVICORN_LOG}." >&2
    return 1
}

run_unit() {
    echo ">>> Unit tests"
    uv run pytest tests/unit/ -v --tb=short
}
run_contracts() {
    echo ">>> Pact and API contract tests"
    uv run pytest tests/contracts/ -v --tb=short
}
run_postgres() {
    echo ">>> PostgreSQL repository integration tests"
    uv run pytest tests/integration/postgres/ -v --tb=short
}
run_browser() {
    echo ">>> Real browser and Crawl4AI integration tests"
    uv run pytest tests/integration/browser/ -v --tb=short
}
run_boundary() {
    echo ">>> Dependency-boundary and scraping integration tests"
    uv run pytest tests/integration/modules/scraping/ tests/integration/boundary/ -v --tb=short
}
run_smoke() {
    echo ">>> Live API HTTP smoke tests"
    start_api_server
    TEST_API_URL="http://127.0.0.1:${TEST_API_PORT:-8000}" \
        uv run pytest tests/integration/smoke/ -v --tb=short
}
run_k6() {
    echo ">>> k6 baseline and unexpected-burst profiles"
    if ! command -v k6 >/dev/null 2>&1; then
        echo "ERROR: k6 is required for this mode; no load checks were executed." >&2
        return 2
    fi
    if [[ -z "${UVICORN_PID}" ]]; then
        start_api_server
    fi
    local base_url="http://127.0.0.1:${TEST_API_PORT:-8000}"
    K6_BASE_URL="${base_url}" \
        K6_API_KEY="${TEST_API_KEY}" \
        K6_SOURCE_IDS="${K6_SOURCE_IDS:-22222222-2222-4222-8222-222222222222}" \
        K6_LOCKED_SOURCE_ID="${K6_LOCKED_SOURCE_ID:-33333333-3333-4333-8333-333333333333}" \
        K6_INACTIVE_SOURCE_ID="${K6_INACTIVE_SOURCE_ID:-44444444-4444-4444-8444-444444444444}" \
        K6_KNOWN_OPERATION_ID="${K6_KNOWN_OPERATION_ID:-11111111-1111-4111-8111-111111111111}" \
        K6_PROFILE=baseline k6 run tests/k6/main.js
    K6_BASE_URL="${base_url}" \
        K6_API_KEY="${TEST_API_KEY}" \
        K6_SOURCE_IDS="${K6_SOURCE_IDS:-22222222-2222-4222-8222-222222222222}" \
        K6_LOCKED_SOURCE_ID="${K6_LOCKED_SOURCE_ID:-33333333-3333-4333-8333-333333333333}" \
        K6_INACTIVE_SOURCE_ID="${K6_INACTIVE_SOURCE_ID:-44444444-4444-4444-8444-444444444444}" \
        K6_KNOWN_OPERATION_ID="${K6_KNOWN_OPERATION_ID:-11111111-1111-4111-8111-111111111111}" \
        K6_PROFILE=unexpected_burst k6 run tests/k6/main.js
}

case "${MODE}" in
    unit) run_unit ;;
    contracts) run_contracts ;;
    postgres) run_postgres ;;
    browser) run_browser ;;
    boundary) run_boundary ;;
    smoke) run_smoke ;;
    k6) run_k6 ;;
    all)
        run_unit
        run_contracts
        run_postgres
        run_browser
        run_boundary
        run_smoke
        run_k6
        ;;
esac

echo "=========================================================="
echo "All requested tests passed for mode '${MODE}'."
echo "=========================================================="
