#!/usr/bin/env bash
# Native PostgreSQL and browser setup for the isolated Codespaces test harness.

set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

TEST_DB_NAME="${TEST_DB_NAME:-afaq_codespaces_test}"
TEST_DB_USER="${TEST_DB_USER:-afaq_test_runner}"
TEST_DB_PORT="${TEST_DB_PORT:-5438}"
PG_DATA_DIR="${PG_DATA_DIR:-${HOME}/.local/share/afaq-codespaces-test-postgres}"
PG_SOCKET_DIR="${PG_SOCKET_DIR:-/tmp}"
TEST_ENV_FILE="${CODESPACES_TEST_ENV_FILE:-${HOME}/.config/afaq-ai-service/codespaces-test.env}"
PG_CLUSTER_ADMIN="$(id -un)"

if [[ ! "${TEST_DB_NAME}" =~ ^[a-z][a-z0-9_]*_test$ ]]; then
    echo "ERROR: TEST_DB_NAME must be a lowercase identifier ending in '_test'." >&2
    exit 1
fi
if [[ ! "${TEST_DB_USER}" =~ ^[a-z][a-z0-9_]*$ ]]; then
    echo "ERROR: TEST_DB_USER must be a lowercase SQL identifier." >&2
    exit 1
fi
if [[ ! "${TEST_DB_PORT}" =~ ^[0-9]{1,5}$ ]] || (( TEST_DB_PORT < 1024 || TEST_DB_PORT > 65535 )); then
    echo "ERROR: TEST_DB_PORT must be an unprivileged TCP port." >&2
    exit 1
fi

# Reuse generated local-only credentials when present; environment-supplied
# values take precedence. The file is outside the repository and mode 0600.
if [[ -n "${DATABASE_URL:-}" || -n "${DIRECT_URL:-}" ]]; then
    echo "ERROR: Unset DATABASE_URL and DIRECT_URL before setup; this script provisions its own isolated local test database." >&2
    exit 1
fi
env_test_api_key="${TEST_API_KEY:-}"
env_db_password="${TEST_DB_PASSWORD:-}"
if [[ -f "${TEST_ENV_FILE}" ]]; then
    # This file is created by this script under the current user's config dir.
    # Refuse group/world-readable files before sourcing shell assignments.
    file_mode="$(stat -c '%a' "${TEST_ENV_FILE}")"
    if [[ "${file_mode}" != "600" && "${file_mode}" != "400" ]]; then
        echo "ERROR: Test environment file must have mode 0600 or 0400." >&2
        exit 1
    fi
    # shellcheck source=/dev/null
    source "${TEST_ENV_FILE}"
fi
TEST_API_KEY="${env_test_api_key:-${TEST_API_KEY:-}}"
TEST_DB_PASSWORD="${env_db_password:-${TEST_DB_PASSWORD:-}}"

echo "=== Checking Python environment ==="
if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: 'uv' must be available in the Codespace PATH." >&2
    exit 1
fi
echo "uv: $(uv --version)"

if ! command -v pg_isready >/dev/null 2>&1 || ! command -v psql >/dev/null 2>&1; then
    echo "PostgreSQL client tools are missing; installing native PostgreSQL packages."
    if ! command -v sudo >/dev/null 2>&1; then
        echo "ERROR: PostgreSQL tools are missing and sudo is unavailable. Install PostgreSQL server/client packages in the Codespace image." >&2
        exit 1
    fi
    sudo apt-get update
    sudo apt-get install -y postgresql postgresql-client
fi

PG_BIN_DIR=""
for candidate in /usr/lib/postgresql/*/bin /usr/bin; do
    if [[ -x "${candidate}/initdb" && -x "${candidate}/postgres" && -x "${candidate}/pg_ctl" ]]; then
        PG_BIN_DIR="${candidate}"
    fi
done
if [[ -z "${PG_BIN_DIR}" ]]; then
    echo "ERROR: PostgreSQL server binaries were not found after package setup." >&2
    exit 1
fi
for tool in createdb pg_ctl initdb; do
    if [[ ! -x "${PG_BIN_DIR}/${tool}" ]]; then
        echo "ERROR: Required PostgreSQL binary '${tool}' is missing." >&2
        exit 1
    fi
done

mkdir -p "${PG_DATA_DIR}" "${PG_SOCKET_DIR}" "$(dirname "${TEST_ENV_FILE}")"
chmod 700 "${PG_DATA_DIR}" "$(dirname "${TEST_ENV_FILE}")"

if [[ ! -f "${PG_DATA_DIR}/PG_VERSION" ]]; then
    if [[ -e "${PG_DATA_DIR}" && -n "$(ls -A "${PG_DATA_DIR}" 2>/dev/null)" ]]; then
        echo "ERROR: PostgreSQL data directory exists but is not an initialized cluster." >&2
        exit 1
    fi
    mkdir -p "${PG_DATA_DIR}"
    chmod 700 "${PG_DATA_DIR}"
    echo "Initializing a private PostgreSQL cluster with peer local auth and SCRAM TCP auth."
    "${PG_BIN_DIR}/initdb" -D "${PG_DATA_DIR}" -U "${PG_CLUSTER_ADMIN}" \
        --auth-local=peer --auth-host=scram-sha-256 >/dev/null
fi

if "${PG_BIN_DIR}/pg_ctl" -D "${PG_DATA_DIR}" status >/dev/null 2>&1; then
    if ! pg_isready -h 127.0.0.1 -p "${TEST_DB_PORT}" >/dev/null 2>&1; then
        echo "ERROR: The private PostgreSQL cluster is running, but not on TEST_DB_PORT. Stop it or set the matching TEST_DB_PORT." >&2
        exit 1
    fi
else
    if pg_isready -h 127.0.0.1 -p "${TEST_DB_PORT}" >/dev/null 2>&1; then
        echo "ERROR: TEST_DB_PORT is already served by a PostgreSQL instance outside this private cluster. Choose a free TEST_DB_PORT." >&2
        exit 1
    fi
    echo "Starting private PostgreSQL on loopback port ${TEST_DB_PORT}."
    "${PG_BIN_DIR}/pg_ctl" -D "${PG_DATA_DIR}" \
        -o "-p ${TEST_DB_PORT} -h 127.0.0.1 -k ${PG_SOCKET_DIR}" \
        -l "${PG_DATA_DIR}/postgres.log" start >/dev/null
fi

ready=false
for _ in $(seq 1 30); do
    if pg_isready -h 127.0.0.1 -p "${TEST_DB_PORT}" >/dev/null 2>&1; then
        ready=true
        break
    fi
    sleep 1
done
if [[ "${ready}" != "true" ]]; then
    echo "ERROR: Private PostgreSQL did not become ready." >&2
    exit 1
fi
served_data_dir="$(psql -X --no-psqlrc -Atq -h "${PG_SOCKET_DIR}" \
    -p "${TEST_DB_PORT}" -U "${PG_CLUSTER_ADMIN}" -d postgres \
    -c 'SHOW data_directory')"
if [[ "$(realpath "${served_data_dir}")" != "$(realpath "${PG_DATA_DIR}")" ]]; then
    echo "ERROR: The PostgreSQL endpoint is not backed by the configured private test cluster." >&2
    exit 1
fi

if [[ -z "${TEST_DB_PASSWORD}" ]]; then
    TEST_DB_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
fi
if [[ -z "${TEST_API_KEY}" ]]; then
    TEST_API_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
fi

# Admin access uses the cluster's Unix socket and peer authentication. The
# application role is non-superuser and can only own the explicitly named test DB.
psql -X --no-psqlrc -v ON_ERROR_STOP=1 -h "${PG_SOCKET_DIR}" \
    -p "${TEST_DB_PORT}" -U "${PG_CLUSTER_ADMIN}" -d postgres \
    -v role_name="${TEST_DB_USER}" -v role_password="${TEST_DB_PASSWORD}" \
    -v db_name="${TEST_DB_NAME}" <<'SQL'
SELECT format(
    'CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %L',
    :'role_name', :'role_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'role_name')
\gexec

SELECT format(
    'ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %L',
    :'role_name', :'role_password'
)
\gexec

SELECT format('CREATE DATABASE %I OWNER %I', :'db_name', :'role_name')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db_name')
\gexec

SELECT format('ALTER DATABASE %I OWNER TO %I', :'db_name', :'role_name')
\gexec
SQL

DATABASE_URL="postgresql://${TEST_DB_USER}:${TEST_DB_PASSWORD}@127.0.0.1:${TEST_DB_PORT}/${TEST_DB_NAME}?sslmode=disable"
DIRECT_URL="${DATABASE_URL}"

# Persist only local test credentials outside the repo so setup and test-runner
# invocations share the same isolated database/API key without logging secrets.
{
    printf 'export TEST_DB_NAME=%q\n' "${TEST_DB_NAME}"
    printf 'export TEST_DB_USER=%q\n' "${TEST_DB_USER}"
    printf 'export TEST_DB_PORT=%q\n' "${TEST_DB_PORT}"
    printf 'export DATABASE_URL=%q\n' "${DATABASE_URL}"
    printf 'export DIRECT_URL=%q\n' "${DIRECT_URL}"
    printf 'export TEST_API_KEY=%q\n' "${TEST_API_KEY}"
} >"${TEST_ENV_FILE}"
chmod 600 "${TEST_ENV_FILE}"
export DATABASE_URL DIRECT_URL TEST_API_KEY TEST_DB_NAME TEST_DB_PORT TEST_DB_USER
export ENVIRONMENT=test

echo "=== Syncing Python dependencies and database schema ==="
uv sync --frozen --all-groups
uv run prisma db push --skip-generate
uv run prisma generate

echo "=== Checking Chromium ==="
if ! uv run python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); b = p.chromium.launch(headless=True); b.close(); p.stop()" >/dev/null 2>&1; then
    uv run playwright install --with-deps chromium
fi

echo "=== Checking k6 ==="
if ! command -v k6 >/dev/null 2>&1; then
    if ! command -v sudo >/dev/null 2>&1 || ! command -v curl >/dev/null 2>&1 || ! command -v gpg >/dev/null 2>&1; then
        echo "ERROR: Installing k6 requires sudo, curl, and gpg in the Codespace." >&2
        exit 1
    fi
    sudo install -d -m 0755 /usr/share/keyrings
    curl -fsSL https://dl.k6.io/key.gpg | sudo gpg --dearmor --yes -o /usr/share/keyrings/k6-archive-keyring.gpg
    echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" \
        | sudo tee /etc/apt/sources.list.d/k6.list >/dev/null
    sudo apt-get update
    sudo apt-get install -y k6
fi
k6 version

echo "=== Seeding isolated test fixtures ==="
uv run python scripts/seed_test_db.py

echo "Setup complete: native PostgreSQL ready at 127.0.0.1:${TEST_DB_PORT}/${TEST_DB_NAME}; credentials stored in a mode-0600 file outside the repository."
