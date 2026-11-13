#!/usr/bin/env bash
# ==============================================================================
# scripts/codespaces_test_setup.sh
# Repeatable, native environment setup for Afaq-AI-Service test execution.
# Follows docs/reports/test_coverage_gap_assessment/codespaces_environment_setup.md
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

echo "=== [1/6] Environment and Tool Discovery ==="
if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: 'uv' package manager is not installed or not in PATH." >&2
    exit 1
fi
echo "✔ uv found: $(uv --version)"

PYTHON_BIN="$(uv run which python3 2>/dev/null || which python3)"
echo "✔ Python binary: ${PYTHON_BIN} ($(${PYTHON_BIN} --version))"

echo "=== [2/6] PostgreSQL Native Service Preparation ==="
# Determine port and connection parameters
TEST_DB_PORT="${TEST_DB_PORT:-5438}"
TEST_DB_NAME="${TEST_DB_NAME:-afaq_codespaces_test}"
TEST_DB_USER="${TEST_DB_USER:-postgres}"

# Safety check: database name must contain 'test'
if [[ "${TEST_DB_NAME}" != *"test"* ]]; then
    echo "ERROR: Refusing to configure non-test database: ${TEST_DB_NAME}" >&2
    exit 1
fi

PG_DATA_DIR="${PG_DATA_DIR:-/tmp/afaq_test_pgdata}"
PG_BIN_DIR=""
for candidate in /usr/lib/postgresql/*/bin /usr/bin; do
    if [[ -x "${candidate}/initdb" && -x "${candidate}/postgres" && -x "${candidate}/pg_ctl" ]]; then
        PG_BIN_DIR="${candidate}"
        break
    fi
done

# Check if PostgreSQL is already responding on TEST_DB_PORT
if pg_isready -h 127.0.0.1 -p "${TEST_DB_PORT}" >/dev/null 2>&1; then
    echo "✔ PostgreSQL already running and accepting connections on port ${TEST_DB_PORT}"
else
    # Try system service first if port is 5432
    if [[ "${TEST_DB_PORT}" == "5432" ]] && command -v sudo >/dev/null 2>&1; then
        sudo service postgresql start >/dev/null 2>&1 || true
    fi

    if pg_isready -h 127.0.0.1 -p "${TEST_DB_PORT}" >/dev/null 2>&1; then
        echo "✔ PostgreSQL service started on port ${TEST_DB_PORT}"
    else
        # Start native user-space cluster
        if [[ -z "${PG_BIN_DIR}" ]]; then
            echo "ERROR: PostgreSQL server binaries (initdb/postgres/pg_ctl) not found." >&2
            exit 1
        fi
        echo "Initializing native PostgreSQL cluster in ${PG_DATA_DIR}..."
        if [[ ! -f "${PG_DATA_DIR}/PG_VERSION" ]]; then
            mkdir -p "${PG_DATA_DIR}"
            "${PG_BIN_DIR}/initdb" -D "${PG_DATA_DIR}" -U "${TEST_DB_USER}" --auth=trust >/dev/null
        fi
        echo "Starting native PostgreSQL on port ${TEST_DB_PORT}..."
        "${PG_BIN_DIR}/pg_ctl" -D "${PG_DATA_DIR}" -o "-p ${TEST_DB_PORT} -k /tmp" -l "/tmp/afaq_pg_${TEST_DB_PORT}.log" start
        sleep 1
    fi
fi

# Verify PostgreSQL readiness
pg_isready -h 127.0.0.1 -p "${TEST_DB_PORT}"

# Create test database if absent
if ! psql -h 127.0.0.1 -p "${TEST_DB_PORT}" -U "${TEST_DB_USER}" -lqt | cut -d \| -f 1 | grep -qw "${TEST_DB_NAME}"; then
    echo "Creating isolated test database: ${TEST_DB_NAME}"
    createdb -h 127.0.0.1 -p "${TEST_DB_PORT}" -U "${TEST_DB_USER}" "${TEST_DB_NAME}"
fi
echo "✔ Test database ready: ${TEST_DB_NAME} on 127.0.0.1:${TEST_DB_PORT}"

# Export test database URL for subsequent steps
export DATABASE_URL="postgresql://${TEST_DB_USER}@127.0.0.1:${TEST_DB_PORT}/${TEST_DB_NAME}?sslmode=disable"
export DIRECT_URL="${DATABASE_URL}"

echo "=== [3/6] Sync Dependencies and Prisma Schema ==="
uv sync --all-groups
uv run prisma db push --skip-generate
uv run prisma generate
echo "✔ Prisma schema pushed and client generated."

echo "=== [4/6] Browser & Crawl4AI Prerequisites ==="
if uv run python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); b = p.chromium.launch(headless=True); b.close(); p.stop()" >/dev/null 2>&1; then
    echo "✔ Chromium browser binary already installed and launchable."
else
    echo "Installing Chromium for Playwright/Crawl4AI..."
    uv run playwright install chromium
    echo "✔ Chromium browser binary installed."
fi

echo "=== [5/6] Ephemeral Test Fixture Seeding ==="
export TEST_API_KEY="${TEST_API_KEY:-k6-test-key-secret-12345}"
uv run python scripts/seed_test_db.py
echo "✔ Ephemeral test fixtures seeded."

echo "=== [6/6] Readiness Verification Summary ==="
echo "----------------------------------------------------"
echo "Target Commit:      $(git rev-parse --short HEAD) ($(git rev-parse --abbrev-ref HEAD))"
echo "PostgreSQL:         READY (127.0.0.1:${TEST_DB_PORT}/${TEST_DB_NAME})"
echo "Python & uv:        READY (${PYTHON_BIN})"
echo "Prisma Client:      READY"
echo "Chromium / Browser: READY"
echo "Test API Key:       CONFIGURED (redacted)"
echo "----------------------------------------------------"
echo "Codespaces test environment setup completed successfully."
