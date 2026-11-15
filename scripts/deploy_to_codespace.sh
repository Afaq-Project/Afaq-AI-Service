#!/usr/bin/env bash
# Sync tracked project files to a Codespace without copying local secrets.

set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPOSITORY="Afaq-Project/Afaq-AI-Service"
TARGET_DIR="/workspaces/Afaq-AI-Service"
cd "${REPO_ROOT}"

for tool in gh git tar; do
    if ! command -v "${tool}" >/dev/null 2>&1; then
        echo "ERROR: Required command '${tool}' is not installed." >&2
        exit 1
    fi
done

CODESPACE_NAME="${CODESPACE_NAME:-}"
if [[ -z "${CODESPACE_NAME}" ]]; then
    mapfile -t matches < <(
        gh codespace list --json name,repository \
            -q ".[] | select(.repository == \"${REPOSITORY}\") | .name"
    )
    if [[ "${#matches[@]}" -ne 1 ]]; then
        echo "ERROR: Expected exactly one Codespace for ${REPOSITORY}; found ${#matches[@]}. Set CODESPACE_NAME explicitly." >&2
        exit 1
    fi
    CODESPACE_NAME="${matches[0]}"
fi

if [[ ! "${CODESPACE_NAME}" =~ ^[A-Za-z0-9-]+$ ]]; then
    echo "ERROR: CODESPACE_NAME contains unsupported characters." >&2
    exit 1
fi

codespace_repo="$(gh codespace list --json name,repository \
    -q ".[] | select(.name == \"${CODESPACE_NAME}\") | .repository")"
if [[ "${codespace_repo}" != "${REPOSITORY}" ]]; then
    echo "ERROR: The selected Codespace does not belong to ${REPOSITORY}." >&2
    exit 1
fi

EXECUTE_TESTS="${EXECUTE_TESTS:-false}"
TEST_MODE="${TEST_MODE:-all}"
if [[ "${EXECUTE_TESTS}" != "true" && "${EXECUTE_TESTS}" != "false" ]]; then
    echo "ERROR: EXECUTE_TESTS must be 'true' or 'false'." >&2
    exit 1
fi
case "${TEST_MODE}" in
    unit|contracts|postgres|browser|boundary|smoke|k6|all) ;;
    *) echo "ERROR: Unsupported TEST_MODE '${TEST_MODE}'." >&2; exit 1 ;;
esac

temporary_dir="$(mktemp -d "${TMPDIR:-/tmp}/afaq-codespace-sync.XXXXXX")"
file_list="${temporary_dir}/tracked-files.list"
cleanup() { rm -rf -- "${temporary_dir}"; }
trap cleanup EXIT INT TERM

# Only tracked files are eligible. Explicitly exclude secret/config material
# even if it was accidentally added to Git in the past.
while IFS= read -r -d '' path; do
    case "${path}" in
        .env|.env.*|*/.env|*/.env.*|.aws/*|*/.aws/*|.ssh/*|*/.ssh/*|\
        *.pem|*.key|*.p12|*.pfx|*credentials*|*/id_rsa*|*/id_ed25519*)
            continue
            ;;
    esac
    [[ -f "${path}" ]] && printf '%s\0' "${path}" >>"${file_list}"
done < <(git ls-files -z --cached)

if [[ ! -s "${file_list}" ]]; then
    echo "ERROR: No tracked working-tree files were found to sync." >&2
    exit 1
fi

echo "Syncing tracked project files to Codespace ${CODESPACE_NAME}."
gh codespace ssh --codespace "${CODESPACE_NAME}" -- true
tar --null --files-from="${file_list}" -czf - | \
    gh codespace ssh --codespace "${CODESPACE_NAME}" -- \
        "set -euo pipefail; mkdir -p '${TARGET_DIR}'; tar --no-same-owner -xzf - -C '${TARGET_DIR}'; echo 'Tracked project files extracted successfully.'"

if [[ "${EXECUTE_TESTS}" == "true" ]]; then
    echo "Preparing the Codespace test environment and running mode '${TEST_MODE}'."
    remote_test_command="set -euo pipefail; cd '${TARGET_DIR}'; bash scripts/codespaces_test_setup.sh; bash scripts/codespaces_test.sh '${TEST_MODE}'"
    gh codespace ssh --codespace "${CODESPACE_NAME}" -- "${remote_test_command}"
else
    echo "Tracked files synced. Local ignored/untracked files and credentials were not transferred."
    echo "To prepare and run later: gh codespace ssh -c ${CODESPACE_NAME} -- bash -lc 'cd ${TARGET_DIR} && bash scripts/codespaces_test_setup.sh && bash scripts/codespaces_test.sh ${TEST_MODE}'"
fi
