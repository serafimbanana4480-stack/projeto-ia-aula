#!/usr/bin/env bash
# NEXUS / LUSO AI — airllm model installer (wrapper)
# Delegates to the Python installer which is the source of truth.
# Kept for backwards compat with existing CI scripts that call this file.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "${SCRIPT_DIR}/install-models.py" ]; then
    python "${SCRIPT_DIR}/install-models.py" "$@"
else
    echo "ERROR: install-models.py not found at ${SCRIPT_DIR}" >&2
    exit 1
fi
