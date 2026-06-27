#!/usr/bin/env bash
# Compat shim → modules/optional/openwebui.sh (use install/spark-install instead)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${ROOT}/modules/optional/openwebui.sh" "$@"
