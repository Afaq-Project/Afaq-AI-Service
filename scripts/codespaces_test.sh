#!/usr/bin/env bash
# ==============================================================================
# scripts/codespaces_test.sh
# Layered test runner for Afaq-AI-Service in Codespaces and local Linux.
# Follows docs/reports/test_coverage_gap_assessment/test_execution_workflow.md
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

MODE="${1:-all}"
COMMIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
BRANCH_NAME="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'unknown')"

echo "=========================================================="
echo "Afaq AI Service - Codespaces Test Runner"
echo "Commit:  ${COMMIT_SHA} (${BRANCH_NAME})"
echo "Mode:    ${MODE}"
echo "Time:    $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "=========================================================="

# Default test database configuration if not provided
TEST_DB_PORT="${TEST_DB_PORT:-5438}"
TEST_DB_NAME="${TEST_DB_NAME:-afaq_codespaces_test}"
TEST_DB_USER="${TEST_DB_USER:-postgres}"

export DATABASE_URL="${DATABASE_URL:-postgresql://${TEST_DB_USER}@127.0.0.1:${TEST_DB_PORT}/${TEST_DB_NAME}?sslmode=disable}"
export DIRECT_URL="${DIRECT_URL:-${DATABASE_URL}}"
export ENVIRONMENT="test"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"
export TEST_API_KEY="${TEST_API_KEY:-k6-test-key-secret-12345}"

# Safety check: database name must contain 'test'
if [[ "${DATABASE_URL}" != *"test"* ]]; then
    echo "ERROR: Refusing to run tests against non-test DATABASE_URL: ${DATABASE_URL}" >&2
    exit 1
fi

UVICORN_PID=""
cleanup() {
    if [[ -n "${UVICORN_PID}" ]]; then
        echo "Stopping test Uvicorn server (PID ${UVICORN_PID})..."
        kill -TERM "${UVICORN_PID}" 2>/dev/null || true
        wait "${UVICORN_PID}" 2>/dev/null || true
        echo "Test server stopped."
    fi
}
trap cleanup EXIT INT TERM

start_api_server() {
    echo "Starting Uvicorn API server on 127.0.0.1:8000..."
    uv run uvicorn src.main:app --host 127.0.0.1 --port 8000 --log-level warning &
    UVICORN_PID=$!

    echo "Waiting for API server readiness at http://127.0.0.1:8000/health..."
    local attempts=0
    local max_attempts=30
    while ! curl -s -f http://127.0.0.1:8000/health >/dev/null 2>&1; do
        sleep 0.5
        attempts=$((attempts + 1))
        if [[ ${attempts} -ge ${max_attempts} ]]; then
            echo "ERROR: API server failed to become healthy within 15 seconds." >&2
            exit 1
        fi
    done
    echo "✔ API server is healthy (PID ${UVICORN_PID})."
}

run_unit() {
    echo ">>> Tier 1: Fast Deterministic Unit Tests"
    uv run pytest tests/unit/ -v --tb=short
}

run_contracts() {
    echo ">>> Tier 2: Contract & Route Endpoint Tests"
    uv run pytest tests/contracts/ -v --tb=short
}

run_postgres() {
    echo ">>> Tier 3: Native PostgreSQL Integration Tests"
    uv run pytest tests/integration/postgres/ -v --tb=short
}

run_browser() {
    echo ">>> Tier 4: Real Browser & Crawl4AI Integration Tests"
    uv run pytest tests/integration/browser/ -v --tb=short
}

run_boundary() {
    echo ">>> Tier 5: External Boundary Integration Tests (S3, LLM, Webhook, DLQ)"
    uv run pytest tests/integration/modules/scraping/ tests/integration/boundary/ -v --tb=short
}

run_smoke() {
    echo ">>> Tier 6: Live API HTTP Smoke Tests"
    start_api_server
    uv run pytest tests/integration/smoke/ -v --tb=short
}

run_k6() {
    echo ">>> Tier 7: k6 Scenarios (Baseline & Unexpected-Burst)"
    if ! command -v k6 >/dev/null 2>&1; then
        echo "WARNING: k6 is not installed. Skipping k6 execution."
        return 0
    fi
    if [[ -z "${UVICORN_PID}" ]]; then
        start_api_server
    fi
    echo "Running k6 main suite..."
    k6 run tests/k6/main.js
}

case "${MODE}" in
    unit)
        run_unit
        ;;
    contracts)
        run_contracts
        ;;
    postgres)
        run_postgres
        ;;
    browser)
        run_browser
        ;;
    boundary)
        run_boundary
        ;;
    smoke)
        run_smoke
        ;;
    k6)
        run_k6
        ;;
    all)
        run_unit
        run_contracts
        run_postgres
        run_browser
        run_boundary
        run_smoke
        run_k6
        ;;
    *)
        echo "Unknown mode: ${MODE}"
        echo "Supported modes: unit, contracts, postgres, browser, boundary, smoke, k6, all"
        exit 1
        ;;
esac

echo "=========================================================="
echo "Test execution finished successfully for mode: ${MODE}"
echo "=========================================================="
