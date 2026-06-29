#!/usr/bin/env bash

set -euo pipefail
trap 'echo "Script $0 failed at line $LINENO" >&2' ERR

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 path/to/example.py" >&2
    exit 2
fi

CALL_DIR="$(pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="${SCRIPT_DIR}"

EXAMPLE_SCRIPT="$1"
if [[ "${EXAMPLE_SCRIPT}" != /* ]]; then
    EXAMPLE_SCRIPT="${CALL_DIR}/${EXAMPLE_SCRIPT}"
fi

if [[ ! -f "${EXAMPLE_SCRIPT}" ]]; then
    echo "Example script not found: ${EXAMPLE_SCRIPT}" >&2
    exit 2
fi

cd "${REPO_ROOT}"
PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}" python "${EXAMPLE_SCRIPT}"
