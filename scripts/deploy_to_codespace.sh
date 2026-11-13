#!/usr/bin/env bash
# ==============================================================================
# scripts/deploy_to_codespace.sh
# Synchronizes local workspace files and tests to GitHub Codespaces and triggers execution.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# Auto-detect or use configured Codespace name
CODESPACE_NAME="${CODESPACE_NAME:-}"
if [[ -z "${CODESPACE_NAME}" ]]; then
    CODESPACE_NAME="$(gh codespace list --json name,repository -q '.[] | select(.repository == "Afaq-Project/Afaq-AI-Service") | .name' | head -n 1)"
fi

if [[ -z "${CODESPACE_NAME}" ]]; then
    echo "ERROR: No active or configured Codespace found for Afaq-Project/Afaq-AI-Service." >&2
    exit 1
fi

echo "=========================================================="
echo "Codespace Deployment & Synchronization"
echo "Target Codespace: ${CODESPACE_NAME}"
echo "Local Directory:  ${REPO_ROOT}"
echo "=========================================================="

# 1. Ensure Codespace is running and reachable
echo "[1/4] Ensuring Codespace is running..."
gh codespace ssh -c "${CODESPACE_NAME}" -- echo "Codespace connection verified."

# 2. Package and synchronize workspace files
echo "[2/4] Packaging and uploading repository files to Codespace..."
TEMP_ARCHIVE="/tmp/afaq_codespace_sync.tar.gz"
tar --exclude='.git' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='node_modules' \
    --exclude='coverage' \
    -czf "${TEMP_ARCHIVE}" .

gh codespace cp -e -c "${CODESPACE_NAME}" "${TEMP_ARCHIVE}" "remote:/tmp/afaq_codespace_sync.tar.gz"
rm -f "${TEMP_ARCHIVE}"

echo "[3/4] Unpacking in Codespace workspace directory..."
gh codespace ssh -c "${CODESPACE_NAME}" -- bash -c '
    set -euo pipefail
    TARGET_DIR="/workspaces/Afaq-AI-Service"
    mkdir -p "${TARGET_DIR}"
    cd "${TARGET_DIR}"
    tar -xzf /tmp/afaq_codespace_sync.tar.gz
    rm -f /tmp/afaq_codespace_sync.tar.gz
    chmod +x scripts/*.sh
    echo "Files successfully synchronized to ${TARGET_DIR}."
'

# 4. Optional execution trigger
EXECUTE_TESTS="${EXECUTE_TESTS:-false}"
TEST_MODE="${TEST_MODE:-all}"

if [[ "${EXECUTE_TESTS}" == "true" ]]; then
    echo "[4/4] Executing test suite in Codespace (Mode: ${TEST_MODE})..."
    gh codespace ssh -c "${CODESPACE_NAME}" -- bash -c "
        set -euo pipefail
        cd /workspaces/Afaq-AI-Service
        bash scripts/codespaces_test_setup.sh
        bash scripts/codespaces_test.sh ${TEST_MODE}
    "
else
    echo "[4/4] Upload complete. To run setup and tests in Codespace, run:"
    echo "  gh codespace ssh -c ${CODESPACE_NAME} -- bash -c 'cd /workspaces/Afaq-AI-Service && bash scripts/codespaces_test_setup.sh && bash scripts/codespaces_test.sh ${TEST_MODE}'"
fi

echo "=========================================================="
echo "Codespace synchronization complete."
echo "=========================================================="
